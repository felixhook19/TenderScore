"""Synthetic tender regression suite (M5 exit criteria).

Scores the full synthetic procurement end-to-end with the deterministic
oracle responder, then asserts:
- recommended scores match the oracle (placeholder oracle — see
  fixtures/synthetic_tender_01/oracle.yaml for the [[HUMAN INPUT NEEDED]]
  flag);
- variance routing escalates the seeded disagreement with no auto score;
- the gate failer is blocked after its Health and Safety score;
- citation validity is at least 99.5%;
- every run replays identically from the record.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.audit.verifier import verify_scope
from app.core.db import tenant_session
from app.core.hashing import content_hash_text
from app.framework.models import CalibrationBenchmark, Criterion
from app.ingestion.storage import set_object_storage
from app.llm_gateway.adapters import DeterministicFakeAdapter
from app.scoring import jobs as scoring_jobs
from app.scoring.engine import prepare_content
from app.scoring.models import Recommendation, ScoringPass, ScoringRun
from app.scoring.orchestrator import create_runs
from app.scoring.replay import replay_run
from tests.conftest import TenantFactory, run_all_jobs
from tests.support.fake_llm import OracleResponder
from tests.support.synthetic import SyntheticTender, build_synthetic_tender, load_oracle

pytestmark = pytest.mark.usefixtures("migrated_database")

LEAF_REFS = ["Q1", "Q2.1", "Q2.2", "Q3.1", "Q3.2", "Q4", "Q5", "Q6"]


@dataclass
class ScoredTender:
    tender: SyntheticTender
    tenant_id: uuid.UUID
    schema: str
    runs: list[ScoringRun]


@pytest.fixture(scope="module")
def scored_tender(migrated_database: None) -> Iterator[ScoredTender]:
    """Build, calibrate and fully score the synthetic tender once."""
    factory = TenantFactory()
    provisioned = factory()
    schema = _schema_for(provisioned.tenant.id)

    session = tenant_session(schema)
    recorder = AuditRecorder(
        session, tenant_id=provisioned.tenant.id, actor_id=None, actor_type="system"
    )
    tender = build_synthetic_tender(
        session, recorder, tenant_schema=schema, reference_suffix="regression"
    )
    set_object_storage(tender.storage)

    # Tokens must exist before the prepared-content hashes are computed:
    # anonymisation output depends on them (idempotent; create_runs re-runs it).
    from app.anonymisation.service import assign_tokens

    assign_tokens(session, recorder, tender.procurement.id)

    # Map prepared content (anonymised, truncated) to oracle scores.
    oracle = load_oracle()
    scores_by_hash: dict[str, int | list[int]] = {}
    for (bidder_key, ref), response in tender.responses_by_key.items():
        criterion = tender.criteria_by_ref[ref]
        prepared, _ = prepare_content(session, response, criterion, tender.procurement.id)
        expected = oracle.get(bidder_key, {}).get(ref)
        if expected is not None:
            scores_by_hash[content_hash_text(prepared)] = expected
    session.commit()

    responder = OracleResponder(scores_by_hash)
    scoring_jobs.set_adapter(DeterministicFakeAdapter(responder))

    # Calibration: two benchmarks within one band of the oracle. The
    # benchmark answers are scored from their raw text, so the oracle map
    # needs entries for those hashes as well.
    q1 = tender.criteria_by_ref["Q1"]
    for key, buyer_score in (("strong", 4), ("weak", 1)):
        scores_by_hash[
            content_hash_text(tender.responses_by_key[(key, "Q1")].text)
        ] = buyer_score
        session.add(
            CalibrationBenchmark(
                procurement_id=tender.procurement.id,
                criterion_id=q1.id,
                title=f"Benchmark ({key})",
                answer_text=tender.responses_by_key[(key, "Q1")].text,
                buyer_score=buyer_score,
            )
        )
    session.flush()
    recorder.record(
        "calibration.benchmark_created",
        entity_type="procurement",
        entity_id=str(tender.procurement.id),
    )
    session.commit()

    from app.llm_gateway.gateway import LLMGateway
    from app.llm_gateway.registry import reconcile, resolve
    from app.scoring.orchestrator import calibrate

    reconcile(session)
    gateway = LLMGateway(DeterministicFakeAdapter(OracleResponder(scores_by_hash)))
    prompt = resolve(session, "score_question_v1")
    calibrate(session, recorder, gateway, prompt, procurement=tender.procurement)
    session.commit()

    runs = create_runs(
        session, recorder, procurement=tender.procurement, created_by=None
    )
    session.commit()
    run_all_jobs(max_seconds=30.0)
    session.expire_all()

    yield ScoredTender(
        tender=tender, tenant_id=provisioned.tenant.id, schema=schema, runs=runs
    )

    scoring_jobs.set_adapter(None)
    set_object_storage(None)
    session.close()
    factory.close()


def _schema_for(tenant_id: uuid.UUID) -> str:
    from app.core.db import get_session_factory
    from app.tenancy.models import Tenant

    session = get_session_factory()()
    try:
        tenant = session.get(Tenant, tenant_id)
        assert tenant is not None
        return tenant.schema_name
    finally:
        session.close()


@pytest.fixture
def db(scored_tender: ScoredTender) -> Iterator[Session]:
    session = tenant_session(scored_tender.schema)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _recommendation_for(
    db: Session, scored: ScoredTender, bidder_key: str, ref: str
) -> Recommendation | None:
    tender = scored.tender
    run = db.scalar(
        select(ScoringRun).where(
            ScoringRun.procurement_id == tender.procurement.id,
            ScoringRun.criterion_id == tender.criteria_by_ref[ref].id,
            ScoringRun.bidder_id == tender.bidders_by_key[bidder_key].id,
        )
    )
    if run is None:
        return None
    return db.scalar(select(Recommendation).where(Recommendation.run_id == run.id))


def test_scores_match_the_oracle(db: Session, scored_tender: ScoredTender) -> None:
    oracle = load_oracle()
    mismatches: list[str] = []
    for bidder_key in ("strong", "mid", "weak"):
        for ref in LEAF_REFS:
            expected = oracle[bidder_key][ref]
            if isinstance(expected, list):
                continue  # the variance case is asserted separately
            recommendation = _recommendation_for(db, scored_tender, bidder_key, ref)
            if recommendation is None or recommendation.score != expected:
                got = recommendation.score if recommendation else "missing"
                mismatches.append(f"{bidder_key}/{ref}: expected {expected}, got {got}")
    assert not mismatches, "Oracle mismatches: " + "; ".join(mismatches)


def test_seeded_disagreement_escalates_without_auto_score(
    db: Session, scored_tender: ScoredTender
) -> None:
    recommendation = _recommendation_for(db, scored_tender, "mid", "Q4")
    assert recommendation is not None
    assert recommendation.confidence_tier == "escalate"
    assert recommendation.score is None
    assert recommendation.variance == 2


def test_gate_failer_is_blocked_after_gate_score(
    db: Session, scored_tender: ScoredTender
) -> None:
    tender = scored_tender.tender
    gate_recommendation = _recommendation_for(db, scored_tender, "gate_failer", "Q6")
    assert gate_recommendation is not None and gate_recommendation.score == 1

    runs = db.scalars(
        select(ScoringRun).where(
            ScoringRun.procurement_id == tender.procurement.id,
            ScoringRun.bidder_id == tender.bidders_by_key["gate_failer"].id,
        )
    ).all()
    blocked = [run for run in runs if run.status == "blocked"]
    assert blocked, "The gate failure must block the bidder's remaining runs."


def test_citation_validity_meets_the_floor(db: Session, scored_tender: ScoredTender) -> None:
    """Citation-validity rate across all recommendations >= 99.5%."""
    recommendations = db.execute(
        select(Recommendation)
        .join(ScoringRun, ScoringRun.id == Recommendation.run_id)
        .where(ScoringRun.procurement_id == scored_tender.tender.procurement.id)
    ).scalars().all()
    total = 0
    verified = 0
    for recommendation in recommendations:
        for citation in recommendation.citations:
            total += 1
            if citation.get("verified"):
                verified += 1
    assert total > 0
    assert verified / total >= 0.995, f"Citation validity {verified}/{total}."


def test_every_run_replays_identically(db: Session, scored_tender: ScoredTender) -> None:
    tender = scored_tender.tender
    runs = db.scalars(
        select(ScoringRun).where(
            ScoringRun.procurement_id == tender.procurement.id,
            ScoringRun.status.in_(["recommended", "escalated"]),
        )
    ).all()
    assert runs
    for run in runs:
        from app.ingestion.models import QuestionResponse

        response = db.get(QuestionResponse, run.question_response_id)
        criterion = db.get(Criterion, run.criterion_id)
        assert response is not None and criterion is not None
        source_text, _ = prepare_content(db, response, criterion, run.procurement_id)
        report = replay_run(db, run, source_text=source_text)
        assert report.identical, f"Run {run.id} replay mismatches: {report.mismatches}"


def test_variance_distribution_is_documented(db: Session, scored_tender: ScoredTender) -> None:
    """The distribution the M9 report documents: everything converges except
    the seeded disagreement."""
    recommendations = db.execute(
        select(Recommendation)
        .join(ScoringRun, ScoringRun.id == Recommendation.run_id)
        .where(ScoringRun.procurement_id == scored_tender.tender.procurement.id)
    ).scalars().all()
    distribution: dict[int, int] = {}
    for recommendation in recommendations:
        distribution[recommendation.variance] = (
            distribution.get(recommendation.variance, 0) + 1
        )
    assert distribution.get(2, 0) == 1, distribution
    assert distribution.get(0, 0) == len(recommendations) - 1, distribution


def test_audit_chain_verifies_after_full_run(db: Session, scored_tender: ScoredTender) -> None:
    report = verify_scope(db, scored_tender.tenant_id)
    assert report.valid, report.detail


def test_passes_run_at_temperature_zero_and_correct_count(
    db: Session, scored_tender: ScoredTender
) -> None:
    """Q1 weighting (15%) meets the high-weight threshold: 5 passes; the
    rest take 3."""
    tender = scored_tender.tender
    for bidder_key, ref, expected_passes in (
        ("strong", "Q1", 5),
        ("strong", "Q5", 3),
    ):
        run = db.scalar(
            select(ScoringRun).where(
                ScoringRun.procurement_id == tender.procurement.id,
                ScoringRun.criterion_id == tender.criteria_by_ref[ref].id,
                ScoringRun.bidder_id == tender.bidders_by_key[bidder_key].id,
            )
        )
        assert run is not None
        assert run.pass_count_target == expected_passes
        passes = db.scalars(
            select(ScoringPass).where(ScoringPass.run_id == run.id)
        ).all()
        assert len(passes) == expected_passes

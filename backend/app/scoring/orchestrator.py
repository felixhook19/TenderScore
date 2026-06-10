"""Scoring orchestration: calibration gate, run creation, gate blocking."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anonymisation.service import assign_tokens
from app.audit.recorder import AuditRecorder
from app.compliance.service import failed_gate_bidders
from app.core.config import get_settings
from app.framework.models import CalibrationBenchmark, Criterion, Procurement
from app.ingestion.models import QuestionResponse, Submission
from app.jobs.queue import enqueue
from app.llm_gateway.gateway import LLMGateway, make_scanned_content
from app.llm_gateway.registry import RegisteredPrompt
from app.scoring.engine import SCORE_PROMPT_ID, ScoringError, passes_for_criterion
from app.scoring.models import ScoringRun
from app.scoring.validation import validate_pass

SCORING_JOB_TYPE = "scoring.run"


class CalibrationGateError(Exception):
    """The calibration gate blocks live scoring; message is safe to show."""


def calibrate(
    session: Session,
    recorder: AuditRecorder,
    gateway: LLMGateway,
    prompt: RegisteredPrompt,
    *,
    procurement: Procurement,
) -> list[CalibrationBenchmark]:
    """Score every benchmark answer once and record the engine scores."""
    benchmarks = session.scalars(
        select(CalibrationBenchmark).where(
            CalibrationBenchmark.procurement_id == procurement.id
        )
    ).all()
    if not benchmarks:
        raise CalibrationGateError(
            "No calibration benchmarks exist. Score two or three benchmark "
            "answers before live scoring can begin."
        )
    for benchmark in benchmarks:
        criterion = session.get(Criterion, benchmark.criterion_id)
        if criterion is None:
            raise CalibrationGateError("A benchmark references a missing criterion.")
        from app.framework.models import BandDescriptor, SpecRequirement
        from app.scoring.engine import _instruction_vars  # shared rendering

        descriptors = session.scalars(
            select(BandDescriptor)
            .where(BandDescriptor.criterion_id == criterion.id)
            .order_by(BandDescriptor.band)
        ).all()
        requirements = session.scalars(
            select(SpecRequirement)
            .where(SpecRequirement.criterion_id == criterion.id)
            .order_by(SpecRequirement.ref)
        ).all()
        valid_bands = {d.band: d.descriptor_text for d in descriptors}

        result = gateway.score(
            session,
            recorder,
            prompt=prompt,
            instruction_vars=_instruction_vars(criterion, descriptors, requirements),
            content_block=make_scanned_content(
                benchmark.answer_text, scan_flagged=False, truncated=False
            ),
            procurement=procurement,
            model_version=procurement.pinned_model_version or "",
        )
        validation = validate_pass(
            result.raw_text, source_text=benchmark.answer_text, valid_bands=valid_bands
        )
        benchmark.engine_score = (
            validation.output.score if validation.valid and validation.output else None
        )
        session.flush()
        recorder.record(
            "calibration.benchmark_scored",
            entity_type="calibration_benchmark",
            entity_id=str(benchmark.id),
            model_version=procurement.pinned_model_version,
        )
    return list(benchmarks)


def check_calibration_gate(session: Session, procurement: Procurement) -> None:
    """Raise unless every benchmark is within one band or its divergence has
    been reviewed and accepted with a recorded rationale."""
    benchmarks = session.scalars(
        select(CalibrationBenchmark).where(
            CalibrationBenchmark.procurement_id == procurement.id
        )
    ).all()
    if not benchmarks:
        raise CalibrationGateError(
            "No calibration benchmarks exist. Score two or three benchmark "
            "answers before live scoring can begin."
        )
    for benchmark in benchmarks:
        if benchmark.engine_score is None:
            raise CalibrationGateError(
                "Calibration has not been run against every benchmark."
            )
        if (
            abs(benchmark.engine_score - benchmark.buyer_score) > 1
            and not benchmark.divergence_accepted
        ):
            raise CalibrationGateError(
                "A calibration benchmark diverges by more than one band and has "
                "not been reviewed. A procurement lead must review the divergence "
                "and record a rationale before scoring can begin."
            )


def create_runs(
    session: Session,
    recorder: AuditRecorder,
    *,
    procurement: Procurement,
    created_by: uuid.UUID | None,
) -> list[ScoringRun]:
    """Create one run per (leaf criterion x bidder response) and enqueue jobs.

    A run is one bidder's answer to one question — never more (CLAUDE.md
    rule 3). Bidders that have failed a gate are blocked, audited.
    """
    if procurement.status != "locked" or procurement.pinned_model_version is None:
        raise ScoringError("The framework must be locked before scoring.")
    check_calibration_gate(session, procurement)
    assign_tokens(session, recorder, procurement.id)

    from app.llm_gateway.registry import resolve

    prompt = resolve(session, SCORE_PROMPT_ID)

    criteria = session.scalars(
        select(Criterion).where(
            Criterion.procurement_id == procurement.id,
            Criterion.price_criterion.is_(False),
        )
    ).all()
    parent_ids = {criterion.parent_id for criterion in criteria if criterion.parent_id}
    leaf_criteria = {
        criterion.id: criterion
        for criterion in criteria
        if criterion.id not in parent_ids
    }

    blocked_bidders = failed_gate_bidders(session, procurement.id)

    responses = session.execute(
        select(QuestionResponse, Submission.bidder_id)
        .join(Submission, Submission.id == QuestionResponse.submission_id)
        .where(Submission.procurement_id == procurement.id)
    ).all()

    # Gate criteria are scored first: their outcome can block the bidder's
    # remaining runs, so they are scheduled marginally ahead of the rest.
    ordered_responses = sorted(
        responses,
        key=lambda row: (
            not (
                row[0].criterion_id is not None
                and row[0].criterion_id in leaf_criteria
                and leaf_criteria[row[0].criterion_id].is_gate
            ),
            str(row[0].id),
        ),
    )

    runs: list[ScoringRun] = []
    for response, bidder_id in ordered_responses:
        criterion = (
            leaf_criteria.get(response.criterion_id)
            if response.criterion_id is not None
            else None
        )
        if criterion is None:
            continue
        existing = session.scalar(
            select(ScoringRun).where(
                ScoringRun.procurement_id == procurement.id,
                ScoringRun.criterion_id == criterion.id,
                ScoringRun.bidder_id == bidder_id,
            )
        )
        if existing is not None:
            continue

        run = ScoringRun(
            procurement_id=procurement.id,
            criterion_id=criterion.id,
            bidder_id=bidder_id,
            question_response_id=response.id,
            status="blocked" if bidder_id in blocked_bidders else "queued",
            pass_count_target=passes_for_criterion(criterion),
            model_version=procurement.pinned_model_version,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            prompt_hash=prompt.sha256_hash,
            content_hash=response.content_hash,
            created_by=created_by,
        )
        session.add(run)
        session.flush()

        if bidder_id in blocked_bidders:
            recorder.record(
                "scoring.run_blocked_gate",
                entity_type="scoring_run",
                entity_id=str(run.id),
            )
            runs.append(run)
            continue

        recorder.record(
            "scoring.run_created",
            entity_type="scoring_run",
            entity_id=str(run.id),
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            model_version=procurement.pinned_model_version,
        )
        enqueue(
            session,
            tenant_id=_tenant_id_of(recorder),
            job_type=SCORING_JOB_TYPE,
            payload={"run_id": str(run.id)},
            # Gate criteria run first: their outcome can block the rest.
            delay_seconds=0.0 if criterion.is_gate else 0.3,
        )
        runs.append(run)
    return runs


def _tenant_id_of(recorder: AuditRecorder) -> uuid.UUID:
    tenant_id = recorder.tenant_id
    if tenant_id is None:
        raise ScoringError("Scoring requires a tenant-scoped recorder.")
    return tenant_id


def high_weight_threshold() -> float:
    return get_settings().high_weight_threshold_pct

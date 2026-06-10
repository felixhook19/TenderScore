"""The scoring engine: multi-pass, temperature 0, deterministic validation,
variance routing.

One run scores one bidder's answer to one question, in strict isolation
(CLAUDE.md rule 3). Pass order of specification requirements is shuffled
deterministically per pass (seeded from run id and pass number) so order
sensitivity is exposed while replays remain bit-identical.
"""

import hashlib
import random
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anonymisation.service import anonymise_text
from app.audit.recorder import AuditRecorder
from app.core.config import get_settings
from app.core.hashing import content_hash_text
from app.framework.models import BandDescriptor, Criterion, Procurement, SpecRequirement
from app.ingestion.models import QuestionResponse, Submission
from app.ingestion.splitter import truncate_to_word_limit
from app.llm_gateway.gateway import GatewayRefusalError, LLMGateway, make_scanned_content
from app.llm_gateway.registry import RegisteredPrompt
from app.scoring.models import Recommendation, ScoringPass, ScoringRun
from app.scoring.validation import ValidationResult, validate_pass

SCORE_PROMPT_ID = "score_question_v1"


class ScoringError(Exception):
    """A run could not be executed; message is safe to show."""


@dataclass(frozen=True)
class RunOutcome:
    run: ScoringRun
    recommendation: Recommendation | None
    validated_scores: list[int]
    variance: int


def passes_for_criterion(criterion: Criterion) -> int:
    settings = get_settings()
    if float(criterion.weighting_pct) >= settings.high_weight_threshold_pct:
        return settings.scoring_passes_high_weight
    return settings.scoring_passes_default


def _ordered_requirements(
    requirements: Sequence[SpecRequirement], run_id: uuid.UUID, pass_number: int
) -> list[SpecRequirement]:
    """Deterministic per-pass shuffle: replayable, order-sensitivity exposing."""
    seed = int.from_bytes(
        hashlib.sha256(f"{run_id}:{pass_number}".encode()).digest()[:8], "big"
    )
    shuffled = list(requirements)
    random.Random(seed).shuffle(shuffled)  # noqa: S311 — deterministic ordering, not crypto
    return shuffled


def _instruction_vars(
    criterion: Criterion,
    descriptors: Sequence[BandDescriptor],
    requirements: Sequence[SpecRequirement],
) -> dict[str, str]:
    descriptor_lines = "\n".join(
        f"Band {descriptor.band} ({descriptor.label}): {descriptor.descriptor_text}"
        for descriptor in descriptors
    )
    requirement_lines = (
        "\n".join(f"{requirement.ref}: {requirement.text}" for requirement in requirements)
        or "None published."
    )
    return {
        "criterion_ref": criterion.ref,
        "criterion_title": criterion.title,
        "band_descriptors": descriptor_lines,
        "spec_requirements": requirement_lines,
    }


def prepare_content(
    session: Session, response: QuestionResponse, criterion: Criterion, procurement_id: uuid.UUID
) -> tuple[str, bool]:
    """Anonymise and truncate the bidder's answer for the scoring context."""
    submission = session.get(Submission, response.submission_id)
    if submission is None:
        raise ScoringError("The response's submission was not found.")
    anonymised = anonymise_text(
        session,
        procurement_id=procurement_id,
        bidder_id=submission.bidder_id,
        text=response.text,
    )
    truncated_text, truncated = truncate_to_word_limit(anonymised, criterion.word_limit)
    return truncated_text, truncated


def execute_run(
    session: Session,
    recorder: AuditRecorder,
    gateway: LLMGateway,
    prompt: RegisteredPrompt,
    *,
    run: ScoringRun,
) -> RunOutcome:
    """Execute every pass for one run and route the result by variance."""
    procurement = session.get(Procurement, run.procurement_id)
    criterion = session.get(Criterion, run.criterion_id)
    response = session.get(QuestionResponse, run.question_response_id)
    if procurement is None or criterion is None or response is None:
        raise ScoringError("The run's procurement, criterion or response is missing.")
    if procurement.pinned_model_version is None:
        raise ScoringError("The framework is not locked; scoring cannot begin.")

    descriptors = session.scalars(
        select(BandDescriptor)
        .where(BandDescriptor.criterion_id == criterion.id)
        .order_by(BandDescriptor.band)
    ).all()
    if not descriptors:
        raise ScoringError("The criterion has no band descriptors.")
    valid_bands = {descriptor.band: descriptor.descriptor_text for descriptor in descriptors}

    requirements = session.scalars(
        select(SpecRequirement)
        .where(SpecRequirement.criterion_id == criterion.id)
        .order_by(SpecRequirement.ref)
    ).all()

    content_text, truncated = prepare_content(session, response, criterion, procurement.id)
    scan_flagged = bool(response.injection_scan.get("flagged", False))

    run.status = "running"
    run.content_hash = content_hash_text(content_text)
    session.flush()

    validated_scores: list[int] = []
    validated_outputs: list[ValidationResult] = []

    for pass_number in range(1, run.pass_count_target + 1):
        result, scoring_pass = _execute_single_pass(
            session,
            recorder,
            gateway,
            prompt,
            run=run,
            procurement=procurement,
            criterion=criterion,
            requirements=requirements,
            descriptors=descriptors,
            content_text=content_text,
            scan_flagged=scan_flagged,
            truncated=truncated,
            valid_bands=valid_bands,
            pass_number=pass_number,
            attempt=1,
        )
        if not result.valid:
            # Failed pass: rejected, rerun once, flag if it fails again.
            result, scoring_pass = _execute_single_pass(
                session,
                recorder,
                gateway,
                prompt,
                run=run,
                procurement=procurement,
                criterion=criterion,
                requirements=requirements,
                descriptors=descriptors,
                content_text=content_text,
                scan_flagged=scan_flagged,
                truncated=truncated,
                valid_bands=valid_bands,
                pass_number=pass_number,
                attempt=2,
            )
            if not result.valid:
                recorder.record(
                    "scoring.pass_flagged",
                    entity_type="scoring_pass",
                    entity_id=str(scoring_pass.id),
                )
        if result.valid and result.output is not None:
            validated_scores.append(result.output.score)
            validated_outputs.append(result)

    if not validated_scores:
        run.status = "failed"
        session.flush()
        recorder.record(
            "scoring.run_failed", entity_type="scoring_run", entity_id=str(run.id)
        )
        return RunOutcome(run=run, recommendation=None, validated_scores=[], variance=0)

    variance = max(validated_scores) - min(validated_scores)
    recommendation = _build_recommendation(
        validated_scores, validated_outputs, variance, valid_bands, run
    )
    session.add(recommendation)
    run.status = "escalated" if recommendation.confidence_tier == "escalate" else "recommended"
    session.flush()
    recorder.record(
        "scoring.recommendation_created",
        entity_type="recommendation",
        entity_id=str(recommendation.id),
        after_hash=content_hash_text(recommendation.justification or ""),
        model_version=run.model_version,
        prompt_id=run.prompt_id,
        prompt_version=run.prompt_version,
    )
    _enforce_gate(session, recorder, run=run, criterion=criterion, recommendation=recommendation)
    return RunOutcome(
        run=run,
        recommendation=recommendation,
        validated_scores=validated_scores,
        variance=variance,
    )


def _enforce_gate(
    session: Session,
    recorder: AuditRecorder,
    *,
    run: ScoringRun,
    criterion: Criterion,
    recommendation: Recommendation,
) -> None:
    """A recommendation below a gate minimum fails the gate: the bidder's
    remaining queued runs are blocked, audited — never silently."""
    from app.compliance.service import gate_minimum

    minimum = gate_minimum(criterion)
    if minimum is None or recommendation.score is None or recommendation.score >= minimum:
        return
    recorder.record("gate.failed", entity_type="bidder", entity_id=str(run.bidder_id))
    pending = session.scalars(
        select(ScoringRun).where(
            ScoringRun.procurement_id == run.procurement_id,
            ScoringRun.bidder_id == run.bidder_id,
            ScoringRun.status == "queued",
        )
    ).all()
    for pending_run in pending:
        pending_run.status = "blocked"
        recorder.record(
            "scoring.run_blocked_gate",
            entity_type="scoring_run",
            entity_id=str(pending_run.id),
        )
    session.flush()


def _execute_single_pass(
    session: Session,
    recorder: AuditRecorder,
    gateway: LLMGateway,
    prompt: RegisteredPrompt,
    *,
    run: ScoringRun,
    procurement: Procurement,
    criterion: Criterion,
    requirements: Sequence[SpecRequirement],
    descriptors: Sequence[BandDescriptor],
    content_text: str,
    scan_flagged: bool,
    truncated: bool,
    valid_bands: dict[int, str],
    pass_number: int,
    attempt: int,
) -> tuple[ValidationResult, ScoringPass]:
    ordered = _ordered_requirements(requirements, run.id, pass_number)
    instruction_vars = _instruction_vars(criterion, descriptors, ordered)
    content_block = make_scanned_content(
        content_text, scan_flagged=scan_flagged, truncated=truncated
    )

    try:
        result = gateway.score(
            session,
            recorder,
            prompt=prompt,
            instruction_vars=instruction_vars,
            content_block=content_block,
            procurement=procurement,
            model_version=run.model_version,
        )
    except GatewayRefusalError as error:
        raise ScoringError(str(error)) from error

    validation = validate_pass(
        result.raw_text, source_text=content_text, valid_bands=valid_bands
    )
    scoring_pass = ScoringPass(
        run_id=run.id,
        pass_number=pass_number,
        attempt=attempt,
        raw_output={"text": result.raw_text},
        validated=validation.valid,
        validation_failures=validation.failures,
        validation_flags=validation.flags,
        score=validation.output.score if validation.valid and validation.output else None,
        injection_suspicion=(
            validation.output.injection_suspicion if validation.output else False
        ),
        latency_ms=result.latency_ms,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        request_hash=result.request_hash,
    )
    session.add(scoring_pass)
    session.flush()
    recorder.record(
        "scoring.pass_recorded",
        entity_type="scoring_pass",
        entity_id=str(scoring_pass.id),
        before_hash=content_block.content_hash,
        after_hash=content_hash_text(result.raw_text),
        prompt_id=result.prompt_id,
        prompt_version=result.prompt_version,
        model_version=result.model_version,
    )
    return validation, scoring_pass


def _build_recommendation(
    validated_scores: list[int],
    validated_outputs: list[ValidationResult],
    variance: int,
    valid_bands: dict[int, str],
    run: ScoringRun,
) -> Recommendation:
    if variance > 1:
        # Beyond one band: escalate to human moderation. No recommended
        # score is auto-presented (CLAUDE.md rule 6).
        return Recommendation(
            run_id=run.id,
            score=None,
            band_label=None,
            justification="",
            citations=[],
            requirements={},
            weaknesses=[],
            variance=variance,
            confidence_tier="escalate",
        )

    counts = Counter(validated_scores)
    top_count = max(counts.values())
    modal_score = min(score for score, count in counts.items() if count == top_count)
    chosen = next(
        result
        for result in validated_outputs
        if result.output is not None and result.output.score == modal_score
    )
    output = chosen.output
    if output is None:  # pragma: no cover — excluded by the comprehension above
        raise ScoringError("A validated pass has no parsed output.")

    return Recommendation(
        run_id=run.id,
        score=modal_score,
        band_label=valid_bands.get(modal_score, "")[:100],
        justification=output.justification,
        citations=[
            {
                "span": citation.span,
                "start": citation.start,
                "end": citation.end,
                "supports": citation.supports,
                "verified": citation.verified,
            }
            for citation in chosen.citations
        ],
        requirements={
            "met": output.requirements.met,
            "partial": output.requirements.partial,
            "not_met": output.requirements.not_met,
        },
        weaknesses=output.weaknesses,
        variance=variance,
        confidence_tier="converged" if variance == 0 else "moderate",
    )

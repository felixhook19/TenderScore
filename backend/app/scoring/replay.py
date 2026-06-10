"""Replay: reproduce a scoring run's validated outputs from the record.

A scoring run is replayable from the audit record (CLAUDE.md rule 2): the
prompt is a hash-verified registry artefact, the content is hash-verified,
requirement order is reseeded identically, and validation is deterministic.
Replay re-validates every stored pass output and re-derives the
recommendation, then compares against what was recorded.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.framework.models import BandDescriptor, Criterion
from app.scoring.models import Recommendation, ScoringPass, ScoringRun
from app.scoring.validation import validate_pass


@dataclass(frozen=True)
class ReplayReport:
    run_id: str
    passes_replayed: int
    identical: bool
    mismatches: list[str]


def replay_run(session: Session, run: ScoringRun, *, source_text: str) -> ReplayReport:
    """Re-validate every recorded pass deterministically and confirm the
    stored validation outcomes and recommendation are reproduced."""
    mismatches: list[str] = []

    criterion = session.get(Criterion, run.criterion_id)
    if criterion is None:
        return ReplayReport(str(run.id), 0, False, ["The criterion no longer exists."])
    descriptors = session.scalars(
        select(BandDescriptor)
        .where(BandDescriptor.criterion_id == criterion.id)
        .order_by(BandDescriptor.band)
    ).all()
    valid_bands = {d.band: d.descriptor_text for d in descriptors}

    passes = session.scalars(
        select(ScoringPass)
        .where(ScoringPass.run_id == run.id)
        .order_by(ScoringPass.pass_number, ScoringPass.attempt)
    ).all()

    for scoring_pass in passes:
        raw = scoring_pass.raw_output or {}
        raw_text = str(raw.get("text", ""))
        revalidated = validate_pass(
            raw_text, source_text=source_text, valid_bands=valid_bands
        )
        if revalidated.valid != scoring_pass.validated:
            mismatches.append(
                f"Pass {scoring_pass.pass_number} (attempt {scoring_pass.attempt}): "
                f"validated={scoring_pass.validated} recorded but replay says "
                f"{revalidated.valid}."
            )
        recorded_score = scoring_pass.score
        replayed_score = (
            revalidated.output.score if revalidated.valid and revalidated.output else None
        )
        if recorded_score != replayed_score:
            mismatches.append(
                f"Pass {scoring_pass.pass_number}: score {recorded_score} recorded "
                f"but replay produced {replayed_score}."
            )

    recommendation = session.scalar(
        select(Recommendation).where(Recommendation.run_id == run.id)
    )
    validated_scores = [
        scoring_pass.score
        for scoring_pass in passes
        if scoring_pass.validated and scoring_pass.score is not None
    ]
    if recommendation is not None and validated_scores:
        variance = max(validated_scores) - min(validated_scores)
        if variance != recommendation.variance:
            mismatches.append(
                f"Variance {recommendation.variance} recorded but replay derived "
                f"{variance}."
            )
        expected_tier = (
            "escalate" if variance > 1 else ("converged" if variance == 0 else "moderate")
        )
        if expected_tier != recommendation.confidence_tier:
            mismatches.append(
                f"Confidence tier '{recommendation.confidence_tier}' recorded but "
                f"replay derived '{expected_tier}'."
            )

    return ReplayReport(
        run_id=str(run.id),
        passes_replayed=len(passes),
        identical=not mismatches,
        mismatches=mismatches,
    )

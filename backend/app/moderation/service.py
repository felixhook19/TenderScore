"""Moderation: tiered queue and confirm/amend decisions.

Named humans confirm or amend every recommendation. Amendments require a
rationale — enforced here, and again by a database CHECK constraint.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.hashing import state_hash
from app.audit.recorder import AuditRecorder
from app.framework.models import BandDescriptor, Criterion
from app.moderation.models import ModerationDecision
from app.scoring.models import Recommendation, ScoringRun


class ModerationError(Exception):
    """Invalid moderation request; message is safe to show."""


# Escalations first: variance routed them to a human, so they need one most.
_TIER_ORDER = {"escalate": 0, "moderate": 1, "converged": 2}


def queue_for_procurement(
    session: Session, procurement_id: uuid.UUID
) -> list[tuple[Recommendation, ScoringRun, bool]]:
    """The moderation queue: every recommendation with whether it is decided,
    ordered escalated -> moderate -> converged."""
    rows = session.execute(
        select(Recommendation, ScoringRun)
        .join(ScoringRun, ScoringRun.id == Recommendation.run_id)
        .where(ScoringRun.procurement_id == procurement_id)
    ).all()
    decided_ids = set(
        session.scalars(
            select(ModerationDecision.recommendation_id).where(
                ModerationDecision.recommendation_id.in_(
                    [recommendation.id for recommendation, _ in rows]
                )
            )
        )
    ) if rows else set()
    entries = [
        (recommendation, run, recommendation.id in decided_ids)
        for recommendation, run in rows
    ]
    entries.sort(
        key=lambda entry: (
            entry[2],  # undecided first
            _TIER_ORDER.get(entry[0].confidence_tier, 3),
            str(entry[1].criterion_id),
        )
    )
    return entries


def decide(
    session: Session,
    recorder: AuditRecorder,
    *,
    recommendation: Recommendation,
    action: str,
    final_score: int | None,
    rationale: str | None,
    decided_by: uuid.UUID,
) -> ModerationDecision:
    """Confirm or amend a recommendation, with a mandatory rationale on amend."""
    existing = session.scalar(
        select(ModerationDecision).where(
            ModerationDecision.recommendation_id == recommendation.id
        )
    )
    if existing is not None:
        raise ModerationError("This recommendation has already been moderated.")

    if action not in ("confirm", "amend"):
        raise ModerationError("The action must be 'confirm' or 'amend'.")

    if action == "confirm":
        if recommendation.score is None:
            raise ModerationError(
                "An escalated recommendation has no score to confirm; record an "
                "amended score with a rationale."
            )
        resolved_score = recommendation.score
    else:
        if final_score is None:
            raise ModerationError("An amendment requires the final score.")
        if not rationale or not rationale.strip():
            raise ModerationError(
                "A rationale is mandatory when amending a recommended score."
            )
        resolved_score = final_score

    run = session.get(ScoringRun, recommendation.run_id)
    if run is None:
        raise ModerationError("The recommendation's scoring run no longer exists.")
    criterion = session.get(Criterion, run.criterion_id)
    if criterion is not None:
        bands = set(
            session.scalars(
                select(BandDescriptor.band).where(
                    BandDescriptor.criterion_id == criterion.id
                )
            )
        )
        if bands and resolved_score not in bands:
            raise ModerationError(
                f"Score {resolved_score} is not a valid band for this criterion."
            )

    decision = ModerationDecision(
        recommendation_id=recommendation.id,
        action=action,
        final_score=resolved_score,
        rationale=rationale.strip() if rationale else None,
        decided_by=decided_by,
    )
    session.add(decision)
    session.flush()
    recorder.record(
        f"moderation.{action}ed" if action == "confirm" else "moderation.amended",
        entity_type="recommendation",
        entity_id=str(recommendation.id),
        before_hash=state_hash({"recommended_score": recommendation.score}),
        after_hash=state_hash({"final_score": resolved_score, "action": action}),
    )
    return decision

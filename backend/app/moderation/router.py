"""Moderation endpoints: tiered queue and confirm/amend."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.auth.deps import CurrentUser, get_tenant_db, get_tenant_recorder, require_roles
from app.auth.roles import Role
from app.framework.models import BandDescriptor, Criterion
from app.moderation import service
from app.moderation.service import ModerationError
from app.scoring.models import Recommendation

router = APIRouter(tags=["moderation"])

_moderator_roles = require_roles(Role.ADMIN, Role.MODERATOR)
_viewer_roles = require_roles(Role.ADMIN, Role.MODERATOR, Role.EVALUATOR, Role.OBSERVER_AUDITOR)


class QueueEntry(BaseModel):
    recommendation_id: uuid.UUID
    run_id: uuid.UUID
    criterion_id: uuid.UUID
    criterion_ref: str
    criterion_title: str
    bidder_id: uuid.UUID
    score: int | None
    confidence_tier: str
    variance: int
    decided: bool


class ModerateRequest(BaseModel):
    action: str = Field(pattern="^(confirm|amend)$")
    final_score: int | None = Field(default=None, ge=0, le=10)
    rationale: str | None = Field(default=None, max_length=4000)


class DecisionOut(BaseModel):
    id: uuid.UUID
    recommendation_id: uuid.UUID
    action: str
    final_score: int
    rationale: str | None


class DescriptorView(BaseModel):
    band: int
    label: str
    descriptor_text: str


class RecommendationDetail(BaseModel):
    recommendation_id: uuid.UUID
    criterion_ref: str
    criterion_title: str
    score: int | None
    band_label: str | None
    justification: str
    citations: list[dict[str, object]]
    requirements: dict[str, list[str]]
    weaknesses: list[str]
    variance: int
    confidence_tier: str
    descriptors: list[DescriptorView]


@router.get(
    "/procurements/{procurement_id}/moderation/queue",
    response_model=list[QueueEntry],
)
def moderation_queue(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_viewer_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> list[QueueEntry]:
    entries = service.queue_for_procurement(db, procurement_id)
    criterion_ids = {run.criterion_id for _, run, _ in entries}
    criteria = {
        criterion.id: criterion
        for criterion in db.scalars(
            select(Criterion).where(Criterion.id.in_(criterion_ids))
        ).all()
    } if criterion_ids else {}
    return [
        QueueEntry(
            recommendation_id=recommendation.id,
            run_id=run.id,
            criterion_id=run.criterion_id,
            criterion_ref=criteria[run.criterion_id].ref if run.criterion_id in criteria else "",
            criterion_title=(
                criteria[run.criterion_id].title if run.criterion_id in criteria else ""
            ),
            bidder_id=run.bidder_id,
            score=recommendation.score,
            confidence_tier=recommendation.confidence_tier,
            variance=recommendation.variance,
            decided=decided,
        )
        for recommendation, run, decided in entries
    ]


@router.get(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationDetail,
)
def recommendation_detail(
    recommendation_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_viewer_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> RecommendationDetail:
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The recommendation was not found.",
        )
    from app.scoring.models import ScoringRun

    run = db.get(ScoringRun, recommendation.run_id)
    criterion = db.get(Criterion, run.criterion_id) if run else None
    descriptors = (
        db.scalars(
            select(BandDescriptor)
            .where(BandDescriptor.criterion_id == criterion.id)
            .order_by(BandDescriptor.band)
        ).all()
        if criterion
        else []
    )
    return RecommendationDetail(
        recommendation_id=recommendation.id,
        criterion_ref=criterion.ref if criterion else "",
        criterion_title=criterion.title if criterion else "",
        score=recommendation.score,
        band_label=recommendation.band_label,
        justification=recommendation.justification,
        citations=recommendation.citations,
        requirements=recommendation.requirements,
        weaknesses=recommendation.weaknesses,
        variance=recommendation.variance,
        confidence_tier=recommendation.confidence_tier,
        descriptors=[
            DescriptorView(
                band=descriptor.band,
                label=descriptor.label,
                descriptor_text=descriptor.descriptor_text,
            )
            for descriptor in descriptors
        ],
    )


@router.post(
    "/recommendations/{recommendation_id}/moderate",
    response_model=DecisionOut,
    status_code=status.HTTP_201_CREATED,
)
def moderate(
    recommendation_id: uuid.UUID,
    body: ModerateRequest,
    user: Annotated[CurrentUser, Depends(_moderator_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> DecisionOut:
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The recommendation was not found.",
        )
    try:
        decision = service.decide(
            db,
            recorder,
            recommendation=recommendation,
            action=body.action,
            final_score=body.final_score,
            rationale=body.rationale,
            decided_by=user.id,
        )
    except ModerationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return DecisionOut(
        id=decision.id,
        recommendation_id=decision.recommendation_id,
        action=decision.action,
        final_score=decision.final_score,
        rationale=decision.rationale,
    )

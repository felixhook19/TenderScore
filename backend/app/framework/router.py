"""Framework endpoints: procurements, lots, criteria tree, lock."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.auth.deps import CurrentUser, get_tenant_db, get_tenant_recorder, require_roles
from app.auth.roles import Role
from app.core.db import tenant_session
from app.framework import service
from app.framework.models import BandDescriptor, Criterion, Lot, Procurement, SpecRequirement
from app.framework.service import FrameworkError, FrameworkLockedError

router = APIRouter(prefix="/procurements", tags=["framework"])

_framework_roles = require_roles(Role.ADMIN, Role.PROCUREMENT_LEAD)


class ProcurementRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    reference: str = Field(min_length=1, max_length=100)
    regime: str = Field(default="PA23", pattern="^(PA23|PCR15)$")


class ProcurementOut(BaseModel):
    id: uuid.UUID
    title: str
    reference: str
    regime: str
    status: str
    pinned_model_version: str | None
    framework_locked_at: datetime | None
    framework_lock_hash: str | None


class LotRequest(BaseModel):
    lot_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)


class LotOut(BaseModel):
    id: uuid.UUID
    lot_number: int
    title: str


class DescriptorIn(BaseModel):
    band: int = Field(ge=0, le=10)
    label: str = Field(min_length=1, max_length=100)
    descriptor_text: str = Field(min_length=1)


class RequirementIn(BaseModel):
    ref: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1)


class CriterionRequest(BaseModel):
    ref: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=300)
    weighting_pct: Decimal = Field(ge=0, le=100)
    lot_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    is_gate: bool = False
    gate_rule: dict[str, object] | None = None
    word_limit: int | None = Field(default=None, ge=1)
    page_limit: int | None = Field(default=None, ge=1)
    price_criterion: bool = False
    descriptors: list[DescriptorIn] = Field(default_factory=list)
    requirements: list[RequirementIn] = Field(default_factory=list)


class CriterionOut(BaseModel):
    id: uuid.UUID
    ref: str
    title: str
    weighting_pct: Decimal
    parent_id: uuid.UUID | None
    lot_id: uuid.UUID | None
    is_gate: bool
    gate_rule: dict[str, object] | None
    word_limit: int | None
    page_limit: int | None
    price_criterion: bool
    descriptors: list[DescriptorIn]
    requirements: list[RequirementIn]


class ProcurementDetail(ProcurementOut):
    lots: list[LotOut]
    criteria: list[CriterionOut]


class LockResponse(BaseModel):
    lock_hash: str
    model_version: str
    detail: str


def _procurement_out(procurement: Procurement) -> ProcurementOut:
    return ProcurementOut(
        id=procurement.id,
        title=procurement.title,
        reference=procurement.reference,
        regime=procurement.regime,
        status=procurement.status,
        pinned_model_version=procurement.pinned_model_version,
        framework_locked_at=procurement.framework_locked_at,
        framework_lock_hash=procurement.framework_lock_hash,
    )


def _load_procurement(db: Session, procurement_id: uuid.UUID) -> Procurement:
    procurement = db.get(Procurement, procurement_id)
    if procurement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The procurement was not found."
        )
    return procurement


def _record_rejected_edit(
    user: CurrentUser, procurement_id: uuid.UUID, attempted: str
) -> None:
    """Audit a post-lock edit attempt in its own committed transaction."""
    session = tenant_session(user.tenant_schema)
    try:
        recorder = AuditRecorder(
            session, tenant_id=user.tenant_id, actor_id=user.id, actor_type="user"
        )
        recorder.record(
            "framework.edit_rejected",
            entity_type="procurement",
            entity_id=str(procurement_id),
            after_hash=None,
            before_hash=None,
            prompt_id=None,
            model_version=attempted[:128],
        )
        session.commit()
    finally:
        session.close()


def _handle_framework_error(
    error: FrameworkError, user: CurrentUser, procurement_id: uuid.UUID, attempted: str
) -> HTTPException:
    if isinstance(error, FrameworkLockedError):
        _record_rejected_edit(user, procurement_id, attempted)
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("", response_model=ProcurementOut, status_code=status.HTTP_201_CREATED)
def create_procurement(
    body: ProcurementRequest,
    user: Annotated[CurrentUser, Depends(_framework_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> ProcurementOut:
    try:
        procurement = service.create_procurement(
            db, recorder, title=body.title, reference=body.reference, regime=body.regime
        )
    except FrameworkError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return _procurement_out(procurement)


@router.get("", response_model=list[ProcurementOut])
def list_procurements(
    user: Annotated[CurrentUser, Depends(require_roles(*Role))],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> list[ProcurementOut]:
    procurements = db.scalars(select(Procurement).order_by(Procurement.created_at)).all()
    return [_procurement_out(procurement) for procurement in procurements]


@router.get("/{procurement_id}", response_model=ProcurementDetail)
def get_procurement(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_roles(*Role))],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> ProcurementDetail:
    procurement = _load_procurement(db, procurement_id)
    lots = db.scalars(
        select(Lot).where(Lot.procurement_id == procurement.id).order_by(Lot.lot_number)
    ).all()
    criteria = db.scalars(
        select(Criterion).where(Criterion.procurement_id == procurement.id).order_by(Criterion.ref)
    ).all()
    out_criteria: list[CriterionOut] = []
    for criterion in criteria:
        descriptors = db.scalars(
            select(BandDescriptor)
            .where(BandDescriptor.criterion_id == criterion.id)
            .order_by(BandDescriptor.band)
        ).all()
        requirements = db.scalars(
            select(SpecRequirement)
            .where(SpecRequirement.criterion_id == criterion.id)
            .order_by(SpecRequirement.ref)
        ).all()
        out_criteria.append(
            CriterionOut(
                id=criterion.id,
                ref=criterion.ref,
                title=criterion.title,
                weighting_pct=criterion.weighting_pct,
                parent_id=criterion.parent_id,
                lot_id=criterion.lot_id,
                is_gate=criterion.is_gate,
                gate_rule=criterion.gate_rule,
                word_limit=criterion.word_limit,
                page_limit=criterion.page_limit,
                price_criterion=criterion.price_criterion,
                descriptors=[
                    DescriptorIn(
                        band=descriptor.band,
                        label=descriptor.label,
                        descriptor_text=descriptor.descriptor_text,
                    )
                    for descriptor in descriptors
                ],
                requirements=[
                    RequirementIn(ref=requirement.ref, text=requirement.text)
                    for requirement in requirements
                ],
            )
        )
    base = _procurement_out(procurement)
    return ProcurementDetail(
        **base.model_dump(),
        lots=[
            LotOut(id=lot.id, lot_number=lot.lot_number, title=lot.title) for lot in lots
        ],
        criteria=out_criteria,
    )


@router.post(
    "/{procurement_id}/lots", response_model=LotOut, status_code=status.HTTP_201_CREATED
)
def add_lot(
    procurement_id: uuid.UUID,
    body: LotRequest,
    user: Annotated[CurrentUser, Depends(_framework_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> LotOut:
    procurement = _load_procurement(db, procurement_id)
    try:
        lot = service.add_lot(
            db, recorder, procurement=procurement, lot_number=body.lot_number, title=body.title
        )
    except FrameworkError as error:
        raise _handle_framework_error(error, user, procurement_id, "lot.create") from error
    return LotOut(id=lot.id, lot_number=lot.lot_number, title=lot.title)


@router.post(
    "/{procurement_id}/criteria",
    response_model=CriterionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_criterion(
    procurement_id: uuid.UUID,
    body: CriterionRequest,
    user: Annotated[CurrentUser, Depends(_framework_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> CriterionOut:
    procurement = _load_procurement(db, procurement_id)
    try:
        criterion = service.add_criterion(
            db,
            recorder,
            procurement=procurement,
            ref=body.ref,
            title=body.title,
            weighting_pct=body.weighting_pct,
            lot_id=body.lot_id,
            parent_id=body.parent_id,
            is_gate=body.is_gate,
            gate_rule=body.gate_rule,
            word_limit=body.word_limit,
            page_limit=body.page_limit,
            price_criterion=body.price_criterion,
            descriptors=[
                (descriptor.band, descriptor.label, descriptor.descriptor_text)
                for descriptor in body.descriptors
            ],
            requirements=[(requirement.ref, requirement.text) for requirement in body.requirements],
        )
    except FrameworkError as error:
        raise _handle_framework_error(error, user, procurement_id, "criterion.create") from error
    return CriterionOut(
        id=criterion.id,
        ref=criterion.ref,
        title=criterion.title,
        weighting_pct=criterion.weighting_pct,
        parent_id=criterion.parent_id,
        lot_id=criterion.lot_id,
        is_gate=criterion.is_gate,
        gate_rule=criterion.gate_rule,
        word_limit=criterion.word_limit,
        page_limit=criterion.page_limit,
        price_criterion=criterion.price_criterion,
        descriptors=body.descriptors,
        requirements=body.requirements,
    )


class ExtractionRequest(BaseModel):
    document_text: str = Field(min_length=1)


class ExtractionDraft(BaseModel):
    draft: dict[str, object]
    detail: str


@router.post("/{procurement_id}/framework/extract", response_model=ExtractionDraft)
def extract_framework_draft(
    procurement_id: uuid.UUID,
    body: ExtractionRequest,
    user: Annotated[CurrentUser, Depends(_framework_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> ExtractionDraft:
    """LLM-assisted extraction *draft*: a human edits every field before the
    framework can be locked. Nothing is written to the framework here."""
    import json

    from app.llm_gateway.gateway import LLMGateway, make_scanned_content
    from app.llm_gateway.registry import resolve
    from app.scoring import jobs as scoring_jobs

    procurement = _load_procurement(db, procurement_id)
    try:
        service.ensure_editable(procurement)
    except FrameworkLockedError as error:
        raise _handle_framework_error(
            error, user, procurement_id, "framework.extract"
        ) from error

    prompt = resolve(db, "framework_extraction_v1")
    gateway = LLMGateway(scoring_jobs._adapter())
    result = gateway.utility(
        db,
        recorder,
        prompt=prompt,
        instruction_vars={},
        content_block=make_scanned_content(
            body.document_text, scan_flagged=False, truncated=False
        ),
        model_version=procurement.pinned_model_version or get_default_model_version(),
    )
    try:
        draft: dict[str, object] = json.loads(result.raw_text)
    except json.JSONDecodeError:
        draft = {"lots": [], "criteria": []}
    return ExtractionDraft(
        draft=draft,
        detail=(
            "This is a draft for review. Edit and confirm every field before "
            "locking the framework; nothing has been saved."
        ),
    )


def get_default_model_version() -> str:
    from app.core.config import get_settings

    return get_settings().pinned_model_version_default


@router.post("/{procurement_id}/framework/lock", response_model=LockResponse)
def lock_framework(
    procurement_id: uuid.UUID,
    request: Request,
    user: Annotated[CurrentUser, Depends(_framework_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> LockResponse:
    procurement = _load_procurement(db, procurement_id)
    try:
        lock_event = service.lock_framework(
            db, recorder, procurement=procurement, locked_by=user.id
        )
    except FrameworkError as error:
        raise _handle_framework_error(error, user, procurement_id, "framework.lock") from error
    return LockResponse(
        lock_hash=lock_event.lock_hash,
        model_version=lock_event.model_version,
        detail=(
            "Framework locked. The criteria tree, descriptors and pinned model "
            "version are now immutable for this procurement."
        ),
    )

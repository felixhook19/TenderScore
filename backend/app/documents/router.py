"""Document endpoints: moderation pack generation and listing."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.auth.deps import CurrentUser, get_tenant_db, get_tenant_recorder, require_roles
from app.auth.roles import Role
from app.documents.jobs import PACK_JOB_TYPE
from app.framework.models import Procurement
from app.jobs.queue import enqueue
from app.moderation.models import ModerationPack

router = APIRouter(tags=["documents"])

_pack_roles = require_roles(Role.ADMIN, Role.PROCUREMENT_LEAD)


class PackRequest(BaseModel):
    format: str = Field(default="docx", pattern="^(docx|pdf)$")


class PackAccepted(BaseModel):
    job_id: uuid.UUID
    detail: str


class PackOut(BaseModel):
    id: uuid.UUID
    version: int
    file_format: str
    object_key: str
    content_hash: str
    generated_at: datetime


@router.post(
    "/procurements/{procurement_id}/packs/moderation",
    response_model=PackAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_pack(
    procurement_id: uuid.UUID,
    body: PackRequest,
    user: Annotated[CurrentUser, Depends(_pack_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> PackAccepted:
    procurement = db.get(Procurement, procurement_id)
    if procurement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The procurement was not found."
        )
    job = enqueue(
        db,
        tenant_id=user.tenant_id,
        job_type=PACK_JOB_TYPE,
        payload={
            "procurement_id": str(procurement_id),
            "format": body.format,
            "generated_by": str(user.id),
        },
    )
    recorder.record(
        "moderation_pack.requested",
        entity_type="procurement",
        entity_id=str(procurement_id),
    )
    return PackAccepted(
        job_id=job.id, detail="Pack generation has been queued and will run shortly."
    )


@router.get(
    "/procurements/{procurement_id}/packs/moderation",
    response_model=list[PackOut],
)
def list_packs(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_pack_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> list[PackOut]:
    packs = db.scalars(
        select(ModerationPack)
        .where(ModerationPack.procurement_id == procurement_id)
        .order_by(ModerationPack.version)
    ).all()
    return [
        PackOut(
            id=pack.id,
            version=pack.version,
            file_format=pack.file_format,
            object_key=pack.object_key,
            content_hash=pack.content_hash,
            generated_at=pack.generated_at,
        )
        for pack in packs
    ]

"""Anonymisation endpoints: the privileged map reveal."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.anonymisation import service
from app.audit.recorder import AuditRecorder
from app.auth.deps import (
    CurrentUser,
    get_tenant_db,
    get_tenant_recorder,
    require_privilege,
)
from app.auth.roles import PRIVILEGE_ANONYMISATION_MAP_READ

router = APIRouter(tags=["anonymisation"])

_map_privilege = require_privilege(PRIVILEGE_ANONYMISATION_MAP_READ)


class MapEntryOut(BaseModel):
    legal_name: str
    token: str


@router.post(
    "/procurements/{procurement_id}/anonymisation/reveal",
    response_model=list[MapEntryOut],
)
def reveal_map(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_map_privilege)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> list[MapEntryOut]:
    """Reveal bidder identities. POST deliberately: every access is a
    recorded, audited act, not a cacheable read."""
    entries = service.reveal_map(db, recorder, procurement_id=procurement_id)
    return [MapEntryOut(legal_name=name, token=token) for name, token in entries]

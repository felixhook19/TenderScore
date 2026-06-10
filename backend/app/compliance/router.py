"""Compliance endpoints: per-procurement compliance overview."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser, get_tenant_db, require_roles
from app.auth.roles import Role
from app.compliance.service import failed_gate_bidders
from app.ingestion.models import QuestionResponse, Submission

router = APIRouter(tags=["compliance"])

_viewer_roles = require_roles(
    Role.ADMIN, Role.PROCUREMENT_LEAD, Role.EVALUATOR, Role.MODERATOR, Role.OBSERVER_AUDITOR
)


class ComplianceEntry(BaseModel):
    submission_id: uuid.UUID
    bidder_id: uuid.UUID
    criterion_ref: str
    compliance_status: str
    notes: list[str]
    word_count: int
    injection_flagged: bool


class ComplianceReport(BaseModel):
    entries: list[ComplianceEntry]
    gate_failed_bidders: list[uuid.UUID]


@router.get(
    "/procurements/{procurement_id}/compliance", response_model=ComplianceReport
)
def compliance_report(
    procurement_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_viewer_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> ComplianceReport:
    rows = db.execute(
        select(QuestionResponse, Submission.bidder_id)
        .join(Submission, Submission.id == QuestionResponse.submission_id)
        .where(Submission.procurement_id == procurement_id)
        .order_by(QuestionResponse.criterion_ref)
    ).all()
    return ComplianceReport(
        entries=[
            ComplianceEntry(
                submission_id=response.submission_id,
                bidder_id=bidder_id,
                criterion_ref=response.criterion_ref,
                compliance_status=response.compliance_status,
                notes=list(response.compliance_notes),
                word_count=response.word_count,
                injection_flagged=bool(response.injection_scan.get("flagged", False)),
            )
            for response, bidder_id in rows
        ],
        gate_failed_bidders=sorted(failed_gate_bidders(db, procurement_id)),
    )

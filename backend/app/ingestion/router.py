"""Ingestion endpoints: bidders, submission upload, ingest job."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.auth.deps import CurrentUser, get_tenant_db, get_tenant_recorder, require_roles
from app.auth.roles import Role
from app.framework.models import Procurement
from app.ingestion import service
from app.ingestion.models import Bidder, QuestionResponse, Submission
from app.ingestion.service import IngestionError
from app.ingestion.storage import get_object_storage
from app.jobs.queue import enqueue

router = APIRouter(tags=["ingestion"])

_ingest_roles = require_roles(Role.ADMIN, Role.PROCUREMENT_LEAD)

INGEST_JOB_TYPE = "submission.ingest"


class BidderRequest(BaseModel):
    legal_name: str = Field(min_length=1, max_length=300)
    companies_house_no: str | None = Field(default=None, max_length=16)


class BidderResponse(BaseModel):
    id: uuid.UUID
    procurement_id: uuid.UUID
    legal_name: str
    companies_house_no: str | None


class SubmissionResponse(BaseModel):
    id: uuid.UUID
    procurement_id: uuid.UUID
    bidder_id: uuid.UUID
    lot_id: uuid.UUID | None
    original_filename: str
    content_hash: str
    status: str


class IngestAccepted(BaseModel):
    job_id: uuid.UUID
    detail: str


class QuestionResponseOut(BaseModel):
    id: uuid.UUID
    criterion_ref: str
    criterion_id: uuid.UUID | None
    word_count: int
    content_hash: str
    compliance_status: str
    injection_flagged: bool


def _bad_request(error: IngestionError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post(
    "/procurements/{procurement_id}/bidders",
    response_model=BidderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_bidder(
    procurement_id: uuid.UUID,
    body: BidderRequest,
    user: Annotated[CurrentUser, Depends(_ingest_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> BidderResponse:
    procurement = db.get(Procurement, procurement_id)
    if procurement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The procurement was not found."
        )
    try:
        bidder = service.create_bidder(
            db,
            recorder,
            procurement=procurement,
            legal_name=body.legal_name,
            companies_house_no=body.companies_house_no,
        )
    except IngestionError as error:
        raise _bad_request(error) from error
    return BidderResponse(
        id=bidder.id,
        procurement_id=bidder.procurement_id,
        legal_name=bidder.legal_name,
        companies_house_no=bidder.companies_house_no,
    )


@router.post(
    "/bidders/{bidder_id}/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_submission(
    bidder_id: uuid.UUID,
    file: UploadFile,
    user: Annotated[CurrentUser, Depends(_ingest_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
    lot_id: uuid.UUID | None = None,
) -> SubmissionResponse:
    bidder = db.get(Bidder, bidder_id)
    if bidder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The bidder was not found."
        )
    data = file.file.read()
    try:
        submission = service.store_submission(
            db,
            recorder,
            get_object_storage(),
            tenant_schema=user.tenant_schema,
            bidder=bidder,
            lot_id=lot_id,
            filename=file.filename or "submission.bin",
            data=data,
            content_type=file.content_type or "application/octet-stream",
        )
    except IngestionError as error:
        raise _bad_request(error) from error
    return SubmissionResponse(
        id=submission.id,
        procurement_id=submission.procurement_id,
        bidder_id=submission.bidder_id,
        lot_id=submission.lot_id,
        original_filename=submission.original_filename,
        content_hash=submission.content_hash,
        status=submission.status,
    )


@router.post(
    "/submissions/{submission_id}/ingest",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_ingest(
    submission_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_ingest_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
    recorder: Annotated[AuditRecorder, Depends(get_tenant_recorder)],
) -> IngestAccepted:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The submission was not found."
        )
    submission.status = "ingesting"
    job = enqueue(
        db,
        tenant_id=user.tenant_id,
        job_type=INGEST_JOB_TYPE,
        payload={"submission_id": str(submission.id)},
    )
    recorder.record(
        "submission.ingest_requested",
        entity_type="submission",
        entity_id=str(submission.id),
    )
    return IngestAccepted(
        job_id=job.id, detail="Ingestion has been queued and will run shortly."
    )


@router.get(
    "/submissions/{submission_id}/responses",
    response_model=list[QuestionResponseOut],
)
def list_responses(
    submission_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(_ingest_roles)],
    db: Annotated[Session, Depends(get_tenant_db)],
) -> list[QuestionResponseOut]:
    responses = db.scalars(
        select(QuestionResponse)
        .where(QuestionResponse.submission_id == submission_id)
        .order_by(QuestionResponse.criterion_ref)
    ).all()
    return [
        QuestionResponseOut(
            id=response.id,
            criterion_ref=response.criterion_ref,
            criterion_id=response.criterion_id,
            word_count=response.word_count,
            content_hash=response.content_hash,
            compliance_status=response.compliance_status,
            injection_flagged=bool(response.injection_scan.get("flagged", False)),
        )
        for response in responses
    ]

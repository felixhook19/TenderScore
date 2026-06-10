"""Ingestion: bidders, submission upload, parse/split/hash/scan."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.hashing import state_hash
from app.audit.recorder import AuditRecorder
from app.core.hashing import content_hash_bytes, content_hash_text
from app.framework.models import Criterion, Procurement
from app.ingestion.injection_scan import scan_text
from app.ingestion.models import Bidder, QuestionResponse, Submission
from app.ingestion.parsers import extract_text
from app.ingestion.splitter import split_into_questions
from app.ingestion.storage import ObjectStorage


class IngestionError(Exception):
    """Raised on invalid ingestion requests; message is safe to show."""


def create_bidder(
    session: Session,
    recorder: AuditRecorder,
    *,
    procurement: Procurement,
    legal_name: str,
    companies_house_no: str | None,
) -> Bidder:
    cleaned = legal_name.strip()
    if not cleaned:
        raise IngestionError("The bidder's legal name must not be empty.")
    bidder = Bidder(
        procurement_id=procurement.id,
        legal_name=cleaned,
        companies_house_no=companies_house_no,
    )
    session.add(bidder)
    session.flush()
    recorder.record(
        "bidder.created",
        entity_type="bidder",
        entity_id=str(bidder.id),
        after_hash=state_hash(
            {"id": bidder.id, "procurement_id": bidder.procurement_id}
        ),
    )
    return bidder


def store_submission(
    session: Session,
    recorder: AuditRecorder,
    storage: ObjectStorage,
    *,
    tenant_schema: str,
    bidder: Bidder,
    lot_id: uuid.UUID | None,
    filename: str,
    data: bytes,
    content_type: str,
) -> Submission:
    if not data:
        raise IngestionError("The submission file is empty.")
    submission_id = uuid.uuid4()
    object_key = (
        f"{tenant_schema}/procurements/{bidder.procurement_id}/bidders/{bidder.id}/"
        f"submissions/{submission_id}/{filename}"
    )
    storage.put(object_key, data, content_type)

    submission = Submission(
        id=submission_id,
        procurement_id=bidder.procurement_id,
        bidder_id=bidder.id,
        lot_id=lot_id,
        original_filename=filename,
        original_object_key=object_key,
        content_hash=content_hash_bytes(data),
    )
    session.add(submission)
    session.flush()
    recorder.record(
        "submission.received",
        entity_type="submission",
        entity_id=str(submission.id),
        after_hash=submission.content_hash,
    )
    return submission


def ingest_submission(
    session: Session,
    recorder: AuditRecorder,
    storage: ObjectStorage,
    *,
    submission_id: uuid.UUID,
) -> list[QuestionResponse]:
    """Parse, split, hash and injection-scan a stored submission."""
    submission = session.get(Submission, submission_id)
    if submission is None:
        raise IngestionError("The submission was not found.")

    data = storage.get(submission.original_object_key)
    if content_hash_bytes(data) != submission.content_hash:
        submission.status = "failed"
        session.flush()
        recorder.record(
            "submission.integrity_failure",
            entity_type="submission",
            entity_id=str(submission.id),
            before_hash=submission.content_hash,
            after_hash=content_hash_bytes(data),
        )
        raise IngestionError(
            "The stored file no longer matches its recorded content hash."
        )

    text = extract_text(submission.original_filename, data)

    expected_refs = list(
        session.scalars(
            select(Criterion.ref).where(
                Criterion.procurement_id == submission.procurement_id
            )
        )
    )
    sections = split_into_questions(text, expected_refs or None)
    if not sections:
        submission.status = "failed"
        session.flush()
        recorder.record(
            "submission.ingest_failed",
            entity_type="submission",
            entity_id=str(submission.id),
        )
        raise IngestionError(
            "No question sections were found in the submission document."
        )

    criterion_ids = {
        ref: criterion_id
        for ref, criterion_id in session.execute(
            select(Criterion.ref, Criterion.id).where(
                Criterion.procurement_id == submission.procurement_id
            )
        )
    }

    responses: list[QuestionResponse] = []
    for section in sections:
        scan = scan_text(section.text)
        response = QuestionResponse(
            submission_id=submission.id,
            criterion_id=criterion_ids.get(section.criterion_ref),
            criterion_ref=section.criterion_ref,
            text=section.text,
            content_hash=content_hash_text(section.text),
            word_count=section.word_count,
            injection_scan=scan.as_json(),
        )
        session.add(response)
        responses.append(response)
    session.flush()

    for response in responses:
        if response.injection_scan.get("flagged"):
            recorder.record(
                "injection.flagged",
                entity_type="question_response",
                entity_id=str(response.id),
                after_hash=response.content_hash,
            )

    submission.status = "ingested"
    session.flush()
    recorder.record(
        "submission.ingested",
        entity_type="submission",
        entity_id=str(submission.id),
        after_hash=state_hash(
            {
                "submission_id": submission.id,
                "responses": sorted(response.content_hash for response in responses),
            }
        ),
    )
    return responses

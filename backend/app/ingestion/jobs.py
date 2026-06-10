"""Ingestion job handlers."""

import uuid

from app.compliance.service import run_compliance_checks
from app.ingestion.service import ingest_submission
from app.ingestion.storage import get_object_storage
from app.jobs.runner import JobContext, register_handler

INGEST_JOB_TYPE = "submission.ingest"


def handle_ingest(context: JobContext) -> None:
    submission_id = uuid.UUID(str(context.payload["submission_id"]))
    ingest_submission(
        context.session,
        context.recorder,
        get_object_storage(),
        submission_id=submission_id,
    )
    run_compliance_checks(context.session, context.recorder, submission_id=submission_id)


def register() -> None:
    register_handler(INGEST_JOB_TYPE, handle_ingest)

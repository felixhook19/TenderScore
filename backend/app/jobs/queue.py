"""Postgres-backed job queue: enqueue, claim (FOR UPDATE SKIP LOCKED),
complete. Identical semantics to a managed queue; swappable at deploy."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.models import Job


def enqueue(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    job_type: str,
    payload: dict[str, object],
    max_attempts: int = 3,
    delay_seconds: float = 0.0,
) -> Job:
    job = Job(
        tenant_id=tenant_id,
        type=job_type,
        payload=payload,
        max_attempts=max_attempts,
        scheduled_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
    )
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session, worker_id: str) -> Job | None:
    """Claim the next due job; returns None when the queue is empty."""
    job = session.scalars(
        select(Job)
        .where(Job.status == "queued", Job.scheduled_at <= datetime.now(UTC))
        .order_by(Job.scheduled_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_by = worker_id
    job.locked_at = datetime.now(UTC)
    session.flush()
    return job


def mark_succeeded(session: Session, job: Job) -> None:
    job.status = "succeeded"
    job.completed_at = datetime.now(UTC)
    session.flush()


def mark_failed(session: Session, job: Job, error: str) -> None:
    """Fail the job, or requeue it while attempts remain."""
    if job.attempts < job.max_attempts:
        job.status = "queued"
        job.locked_by = None
        job.locked_at = None
        job.error = error
    else:
        job.status = "failed"
        job.completed_at = datetime.now(UTC)
        job.error = error
    session.flush()

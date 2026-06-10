"""Job execution: handler registry and the run loop body.

Each job runs in its tenant's schema context with a system-actor audit
recorder; the job's domain effects and audit events commit atomically,
and the job lifecycle itself is audited.
"""

import logging
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.core.db import get_session_factory, tenant_session
from app.jobs.models import Job
from app.jobs.queue import claim_next, mark_failed, mark_succeeded
from app.tenancy.models import Tenant

logger = logging.getLogger("tenderscore.jobs")


@dataclass(frozen=True)
class JobContext:
    session: Session
    recorder: AuditRecorder
    tenant_id: uuid.UUID
    payload: dict[str, object]


JobHandler = Callable[[JobContext], None]

_HANDLERS: dict[str, JobHandler] = {}


def register_handler(job_type: str, handler: JobHandler) -> None:
    _HANDLERS[job_type] = handler


def registered_types() -> set[str]:
    return set(_HANDLERS)


def run_one(worker_id: str) -> bool:
    """Claim and run a single job. Returns False when the queue is empty."""
    platform_session = get_session_factory()()
    try:
        job = claim_next(platform_session, worker_id)
        if job is None:
            return False
        platform_session.commit()
        _execute(platform_session, job)
        return True
    finally:
        platform_session.close()


def _execute(platform_session: Session, job: Job) -> None:
    handler = _HANDLERS.get(job.type)
    schema_name = platform_session.scalar(
        select(Tenant.schema_name).where(Tenant.id == job.tenant_id)
    )

    if handler is None or schema_name is None:
        error = (
            f"No handler registered for job type '{job.type}'."
            if handler is None
            else f"Tenant {job.tenant_id} has no schema."
        )
        mark_failed(platform_session, job, error)
        platform_session.commit()
        logger.error("Job %s failed: %s", job.id, error)
        return

    work_session = tenant_session(schema_name)
    recorder = AuditRecorder(
        work_session, tenant_id=job.tenant_id, actor_id=None, actor_type="system"
    )
    try:
        handler(JobContext(work_session, recorder, job.tenant_id, dict(job.payload)))
        recorder.record(
            "job.succeeded", entity_type="job", entity_id=str(job.id)
        )
        work_session.commit()
        mark_succeeded(platform_session, job)
        platform_session.commit()
    except Exception:
        work_session.rollback()
        error = traceback.format_exc(limit=8)
        failure_recorder = AuditRecorder(
            work_session, tenant_id=job.tenant_id, actor_id=None, actor_type="system"
        )
        failure_recorder.record("job.failed", entity_type="job", entity_id=str(job.id))
        work_session.commit()
        mark_failed(platform_session, job, error)
        platform_session.commit()
        logger.exception("Job %s (%s) failed.", job.id, job.type)
    finally:
        work_session.close()

"""Worker entrypoint: polls the Postgres-backed queue and runs handlers."""

import logging
import signal
import socket
import time
import uuid
from types import FrameType

from app.jobs.runner import registered_types, run_one

logger = logging.getLogger("tenderscore.worker")

POLL_INTERVAL_SECONDS = 2.0

_shutdown_requested = False


def _request_shutdown(signum: int, _frame: FrameType | None) -> None:
    global _shutdown_requested
    logger.info("Received signal %s — shutting down after current cycle.", signum)
    _shutdown_requested = True


def register_all_handlers() -> None:
    """Import and register every module's job handlers."""
    from app.documents import jobs as document_jobs
    from app.ingestion import jobs as ingestion_jobs
    from app.scoring import jobs as scoring_jobs

    ingestion_jobs.register()
    scoring_jobs.register()
    document_jobs.register()


def run() -> None:
    """Run the worker loop until a termination signal arrives."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    register_all_handlers()

    # Reconcile the prompt registry exactly as the API does: a changed
    # artefact without a version bump must fail startup here too.
    from app.core.config import get_settings
    from app.core.db import get_session_factory
    from app.llm_gateway.registry import reconcile
    from app.llm_gateway.safety import assert_provider_safety

    assert_provider_safety(get_settings())
    session = get_session_factory()()
    try:
        reconcile(session)
    finally:
        session.close()

    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    logger.info(
        "TenderScore worker %s started — handling job types: %s",
        worker_id,
        ", ".join(sorted(registered_types())),
    )
    while not _shutdown_requested:
        try:
            if not run_one(worker_id):
                time.sleep(POLL_INTERVAL_SECONDS)
        except Exception:
            logger.exception("Worker cycle failed; continuing.")
            time.sleep(POLL_INTERVAL_SECONDS)
    logger.info("TenderScore worker stopped.")


if __name__ == "__main__":
    run()

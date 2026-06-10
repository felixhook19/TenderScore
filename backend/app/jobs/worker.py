"""Worker entrypoint.

M0 scope: a process that starts, reports itself healthy and idles. The
Postgres-backed job queue (`jobs` table, `FOR UPDATE SKIP LOCKED` semantics)
is built in M1+ alongside the audit spine; no job types exist yet and no
business logic belongs here until then.
"""

import logging
import signal
import time
from types import FrameType

logger = logging.getLogger("tenderscore.worker")

POLL_INTERVAL_SECONDS = 5.0

_shutdown_requested = False


def _request_shutdown(signum: int, _frame: FrameType | None) -> None:
    global _shutdown_requested
    logger.info("Received signal %s — shutting down after current cycle.", signum)
    _shutdown_requested = True


def run() -> None:
    """Run the worker loop until a termination signal arrives."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    logger.info("TenderScore worker started — no job types registered yet (pre-M1 scaffold).")
    while not _shutdown_requested:
        time.sleep(POLL_INTERVAL_SECONDS)
    logger.info("TenderScore worker stopped.")


if __name__ == "__main__":
    run()

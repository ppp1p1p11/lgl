"""Background worker entrypoint: `python -m legalos.worker`."""

import logging
import os
import signal
import socket
import time
from types import FrameType

from legalos.config import get_settings
from legalos.core.logging import configure_logging
from legalos.jobs import handlers  # noqa: F401  (registers job handlers)
from legalos.jobs.queue import run_one

logger = logging.getLogger("legalos.worker")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stopping = False

    def stop(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("worker started", extra={"worker_id": worker_id})

    while not stopping:
        try:
            did_work = run_one(worker_id)
        except Exception:
            logger.exception("worker loop error")
            did_work = False
        if not did_work:
            time.sleep(settings.worker_poll_seconds)
    logger.info("worker stopped", extra={"worker_id": worker_id})


if __name__ == "__main__":
    main()

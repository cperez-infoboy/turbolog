"""Standalone entrypoint for the dedicated scheduler container.

Run with ``python -m app.scheduler_runner``. If ``settings.ENABLE_SCHEDULER`` is
False, logs and exits immediately (the web container sets this to keep the
scheduler off). Otherwise:

1. Register SIGINT/SIGTERM handlers that set an asyncio.Event (graceful ``docker
   stop``). Registration happens INSIDE ``main()`` (not at module import) so the
   module imports cleanly without a running loop.
2. Start the scheduler (idempotent).
3. ``await stop.wait()`` keeps the loop alive until a signal fires.
4. Shut the scheduler down.

Not unit-tested (it's a process entrypoint), but imports cleanly.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.config import settings
from app.jobs.engine import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("turbolog.scheduler_runner")


async def main() -> None:
    """Run the scheduler until SIGINT/SIGTERM, then shut down gracefully."""
    if not settings.ENABLE_SCHEDULER:
        logger.info("ENABLE_SCHEDULER is False; scheduler runner exiting")
        return

    logger.info("Scheduler runner up (tz=%s, reminder=%s)",
                settings.AUDIT_TIMEZONE, settings.REMINDER_TIME)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    start_scheduler()
    try:
        await stop.wait()
    finally:
        await shutdown_scheduler()
        logger.info("Scheduler runner stopped")


if __name__ == "__main__":
    asyncio.run(main())

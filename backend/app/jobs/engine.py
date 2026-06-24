"""APScheduler engine: owns the lifecycle of the AsyncIOScheduler.

Two functions, both module-level so they can be called from the runner or
from app startup:

- :func:`start_scheduler` — idempotent: returns the existing scheduler if one
  is already running; otherwise builds one, registers every job from
  :func:`app.jobs.registry.build_jobs`, starts it, and caches it.
- :func:`shutdown_scheduler` — async; shuts the scheduler down (no wait) and
  clears the cache.

Uses APScheduler 3.x (``AsyncIOScheduler``) so jobs run as coroutines on the
event loop and can ``await async_session()``. Not unit-tested (APScheduler
itself isn't under test), but imports cleanly.
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.jobs.registry import build_jobs

logger = logging.getLogger("turbolog.scheduler")

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    """Start (or return the already-running) AsyncIOScheduler with all jobs.

    Idempotent: if a scheduler is already cached and running, return it without
    re-adding jobs (``replace_existing=True`` also makes re-adds safe).
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.AUDIT_TIMEZONE))
    for spec in build_jobs():
        scheduler.add_job(
            spec.func,
            spec.trigger,
            args=spec.args,
            id=spec.id,
            replace_existing=True,
            coalesce=spec.coalesce,
            misfire_grace_time=spec.misfire_grace_time,
            max_instances=spec.max_instances,
        )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started with %d job(s)", len(scheduler.get_jobs()))
    return scheduler


async def shutdown_scheduler() -> None:
    """Shut the scheduler down without waiting for running jobs, then clear it."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler shut down")

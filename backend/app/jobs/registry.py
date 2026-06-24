"""Job registry: the single point of extension for scheduled jobs.

Each job is a :class:`JobSpec` describing its id, callable, APScheduler trigger,
and tuning knobs (coalesce, misfire grace, max instances). :func:`build_jobs`
returns the full list; add a future job by appending another ``JobSpec`` here.

Uses APScheduler 3.x API (``CronTrigger``). Not unit-tested — APScheduler itself
isn't under test — but the module imports cleanly so the engine can wire it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.jobs.reminder import run_reminder_job
from app.services.notifier import build_notifier


@dataclass
class JobSpec:
    """Declarative description of a scheduled job.

    Attributes mirror the kwargs ``scheduler.add_job`` consumes, so the engine
    can apply them generically.
    """

    id: str
    func: Callable[..., Any]
    trigger: CronTrigger
    args: list = field(default_factory=list)
    coalesce: bool = True
    misfire_grace_time: int = 3600
    max_instances: int = 1


def _parse_reminder_time(s: str) -> tuple[int, int]:
    """Parse a "HH:MM" 24h string into an (hour, minute) tuple."""
    hh, mm = s.split(":")
    return int(hh), int(mm)


def build_jobs(_settings=settings) -> list[JobSpec]:
    """Return the list of scheduled jobs for the given settings.

    Currently only the daily status reminder (weekdays at REMINDER_TIME in
    AUDIT_TIMEZONE). To add a job, append a new ``JobSpec`` to the returned list.
    """
    tz = ZoneInfo(settings.AUDIT_TIMEZONE)
    hh, mm = _parse_reminder_time(settings.REMINDER_TIME)
    return [
        JobSpec(
            id="daily-status-reminder",
            func=run_reminder_job,
            trigger=CronTrigger(
                day_of_week="mon-fri", hour=hh, minute=mm, timezone=tz
            ),
            args=[build_notifier(settings)],
        ),
    ]

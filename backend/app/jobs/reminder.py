"""Reminder job: notify audited users who haven't closed their day.

Two pure-async functions, no APScheduler import (so they unit-test in isolation):

- :func:`process_user_for_reminder` — per-user: if a DailyClosure exists for
  today, the user already closed (no reminder); otherwise compute their
  current-month summary and remind them.
- :func:`run_reminder_job` — iterate ONLY ``is_audited=True`` users, swallow
  per-user exceptions (log), and emit a summary line.

Both functions open their own session via the injected ``session_factory``
(the module-level ``async_session`` in production; rebound in tests).
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.daily_closure import DailyClosure
from app.models.user import User
from app.services.audit_service import _today_in_tz, compute_user_month_summary

logger = logging.getLogger("turbolog.reminder")


async def process_user_for_reminder(session_factory, user, today: date, notifier) -> bool:
    """Check a single user and remind them if today is not yet closed.

    Returns True if a reminder was sent, False if the user already closed today.

    Opens its own session via ``session_factory`` (the factory, not a session)
    to check for a DailyClosure(user, today). The summary computation also
    receives the factory because the audit service opens its own session.
    """
    async with session_factory() as session:
        result = await session.execute(
            select(DailyClosure).where(
                DailyClosure.user_id == user.id,
                DailyClosure.report_date == today.isoformat(),
            )
        )
        if result.scalar_one_or_none() is not None:
            return False

    summary = await compute_user_month_summary(session_factory, user.id, today=today)
    await notifier.remind(user, today, summary)
    return True


async def run_reminder_job(notifier) -> None:
    """Iterate every is_audited=True user and remind those who haven't closed today.

    Per-user exceptions are swallowed (logged) so one failing user never blocks
    the rest. Emits a summary log line at the end.
    """
    today = _today_in_tz(settings.AUDIT_TIMEZONE)

    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_audited.is_(True)))
        users = result.scalars().all()

    reminded = 0
    total = len(users)
    for user in users:
        try:
            sent = await process_user_for_reminder(async_session, user, today, notifier)
            if sent:
                reminded += 1
        except Exception:
            logger.exception("Reminder failed for user %s (%s)", user.id, user.email)

    logger.info("Reminder job done: %d/%d reminded", reminded, total)

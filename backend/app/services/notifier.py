"""Notifier seam for reminders.

v1 ships only `LogNotifier` (writes to stdout/logger). The `Notifier` Protocol
keeps the door open for an SMTP implementation without changing call sites.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Protocol


class Notifier(Protocol):
    """Reminder delivery interface (duck-typed)."""

    async def remind(self, user, report_date: date, summary) -> None:
        """Send a reminder to ``user`` for ``report_date``.

        ``summary`` is any object exposing ``reported_days`` and ``faltas``
        (the real UserSummary lands in a later layer).
        """
        ...


class LogNotifier:
    """Writes reminder lines to a logger (mode="log")."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("turbolog.notifier")

    async def remind(self, user, report_date: date, summary) -> None:
        who = getattr(user, "email", None) or getattr(user, "name", "user")
        reported = getattr(summary, "reported_days", "?")
        faltas = getattr(summary, "faltas", "?")
        self._logger.info(
            "RECORDATORIO -> %s | fecha=%s | reportados=%s faltas=%s",
            who,
            report_date.isoformat(),
            reported,
            faltas,
        )


def build_notifier(settings) -> Notifier:
    """Build the notifier selected by ``settings.NOTIFIER_MODE``.

    ``"log"`` returns :class:`LogNotifier`. ``"smtp"`` is reserved for a future
    implementation; until then it falls back to :class:`LogNotifier` so the app
    keeps working instead of crashing.
    """
    mode = getattr(settings, "NOTIFIER_MODE", "log")
    if mode == "log":
        return LogNotifier()
    # Future: "smtp" -> SmtpNotifier(settings).
    # Until SMTP lands, any other value degrades gracefully to log.
    return LogNotifier()

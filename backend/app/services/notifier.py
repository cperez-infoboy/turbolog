"""Notifier seam for reminders.

Ships ``LogNotifier`` (stdout) and ``TelegramNotifier`` (Bot API). The
``Notifier`` Protocol keeps the door open for additional channels.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Protocol

import httpx

logger = logging.getLogger("turbolog.notifier")


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

    def __init__(self, _logger: logging.Logger | None = None) -> None:
        self._logger = _logger or logging.getLogger("turbolog.notifier")

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


class TelegramNotifier:
    """Sends reminders via Telegram Bot API (mode="telegram")."""

    def __init__(self, bot_token: str) -> None:
        self._token = bot_token
        self._api = f"https://api.telegram.org/bot{bot_token}"

    async def remind(self, user, report_date: date, summary) -> None:
        chat_id = getattr(user, "telegram_chat_id", None)
        if not chat_id:
            logger.debug(
                "Skipping Telegram reminder for %s — no chat_id",
                getattr(user, "email", "user"),
            )
            return

        name = getattr(user, "name", "user")
        reported = getattr(summary, "reported_days", "?")
        faltas = getattr(summary, "faltas", "?")

        text = (
            f"📋 Recordatorio Turbolog\n"
            f"Hola {name}, no has cerrado el día ({report_date.isoformat()}).\n"
            f"Reportados: {reported} | Faltas: {faltas}"
        )

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._api}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Telegram sendMessage failed for %s: %s %s",
                        chat_id,
                        resp.status_code,
                        resp.text,
                    )
        except Exception:
            logger.exception("Telegram sendMessage error for %s", chat_id)


def build_notifier(settings) -> Notifier:
    """Build the notifier selected by ``settings.NOTIFIER_MODE``.

    ``"log"`` returns :class:`LogNotifier`. ``"telegram"`` returns
    :class:`TelegramNotifier`. Unknown modes fall back to log.
    """
    mode = getattr(settings, "NOTIFIER_MODE", "log")
    if mode == "telegram":
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if token:
            return TelegramNotifier(bot_token=token)
        logger.warning("NOTIFIER_MODE=telegram but TELEGRAM_BOT_TOKEN is empty, falling back to log")
        return LogNotifier()
    if mode == "log":
        return LogNotifier()
    return LogNotifier()

"""Tests for the Notifier seam (LogNotifier).

LogNotifier.remind logs a line containing the user's email, the report date,
and the summary counts. Verified via pytest caplog at INFO level.
"""
import logging
from datetime import date

import pytest

from app.services.notifier import LogNotifier, TelegramNotifier, build_notifier


class _FakeSummary:
    """Minimal stand-in exposing the two attributes remind() reads."""

    def __init__(self, reported_days, faltas):
        self.reported_days = reported_days
        self.faltas = faltas


class _FakeUser:
    def __init__(self, email, name="Someone"):
        self.email = email
        self.name = name


class TestLogNotifierRemind:
    async def test_logs_email_and_counts(self, caplog):
        notifier = LogNotifier()
        user = _FakeUser(email="dev@example.com")
        summary = _FakeSummary(reported_days=12, faltas=3)

        with caplog.at_level(logging.INFO, logger="turbolog.notifier"):
            await notifier.remind(user, date(2026, 6, 24), summary)

        # At least one record at INFO.
        messages = [r.getMessage() for r in caplog.records]
        assert any("dev@example.com" in m for m in messages)
        assert any("reportados=12" in m for m in messages)
        assert any("faltas=3" in m for m in messages)
        assert any("2026-06-24" in m for m in messages)

    async def test_recordatorio_prefix_present(self, caplog):
        notifier = LogNotifier()
        user = _FakeUser(email="x@example.com")
        summary = _FakeSummary(reported_days=0, faltas=5)

        with caplog.at_level(logging.INFO, logger="turbolog.notifier"):
            await notifier.remind(user, date(2026, 6, 24), summary)

        messages = [r.getMessage() for r in caplog.records]
        assert any(m.startswith("RECORDATORIO") for m in messages)


class TestBuildNotifier:
    def test_log_mode_returns_log_notifier(self):
        class _S:
            NOTIFIER_MODE = "log"

        n = build_notifier(_S())
        assert isinstance(n, LogNotifier)

    def test_unknown_mode_falls_back_to_log(self):
        class _S:
            NOTIFIER_MODE = "smtp"

        n = build_notifier(_S())
        assert isinstance(n, LogNotifier)

    def test_telegram_mode_returns_telegram_notifier(self):
        class _S:
            NOTIFIER_MODE = "telegram"
            TELEGRAM_BOT_TOKEN = "fake-token"

        n = build_notifier(_S())
        assert isinstance(n, TelegramNotifier)

    def test_telegram_mode_empty_token_falls_back_to_log(self):
        class _S:
            NOTIFIER_MODE = "telegram"
            TELEGRAM_BOT_TOKEN = ""

        n = build_notifier(_S())
        assert isinstance(n, LogNotifier)

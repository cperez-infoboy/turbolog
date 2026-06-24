"""Tests for the reminder job core logic (RED phase).

The job is split into two pure-async functions (no APScheduler import here):
- process_user_for_reminder: per-user check + notify.
- run_reminder_job: iterate is_audited=True users, swallow per-user errors.
"""
import secrets
from datetime import date

import pytest

from app.jobs import reminder as reminder_module
from app.models.daily_closure import DailyClosure
from app.models.user import User


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeNotifier:
    """Captures remind() calls; optionally raises for a specific email."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.raise_for: str | None = None

    async def remind(self, user, report_date, summary) -> None:
        if self.raise_for is not None and getattr(user, "email", None) == self.raise_for:
            raise RuntimeError(f"boom for {user.email}")
        self.calls.append((user, report_date, summary))


async def _seed_user(
    session_factory,
    email: str,
    *,
    is_audited: bool = True,
) -> User:
    async with session_factory() as s:
        user = User(
            google_sub=f"sub-{email}",
            email=email,
            name=email.split("@")[0],
            is_audited=is_audited,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _seed_closure(session_factory, user_id: str, day: date) -> None:
    async with session_factory() as s:
        s.add(
            DailyClosure(
                id=secrets.token_hex(16),
                user_id=user_id,
                report_date=day.isoformat(),
                finalized_at="2026-06-22T00:00:00+00:00",
            )
        )
        await s.commit()


# --------------------------------------------------------------------------- #
# process_user_for_reminder
# --------------------------------------------------------------------------- #


class TestProcessUserForReminder:
    async def test_user_with_closure_not_reminded(self, session_factory, monkeypatch):
        # Pin today so the closure check is deterministic.
        today = date(2026, 6, 22)  # Monday
        monkeypatch.setattr(reminder_module, "async_session", session_factory)

        user = await _seed_user(session_factory, "closed@x.com")
        await _seed_closure(session_factory, user.id, today)

        notifier = _FakeNotifier()
        sent = await reminder_module.process_user_for_reminder(
            session_factory, user, today, notifier
        )
        assert sent is False
        assert notifier.calls == []

    async def test_user_without_closure_is_reminded(
        self, session_factory, monkeypatch
    ):
        today = date(2026, 6, 22)  # Monday
        monkeypatch.setattr(reminder_module, "async_session", session_factory)

        user = await _seed_user(session_factory, "open@x.com")
        notifier = _FakeNotifier()

        sent = await reminder_module.process_user_for_reminder(
            session_factory, user, today, notifier
        )
        assert sent is True
        assert len(notifier.calls) == 1
        called_user, called_date, called_summary = notifier.calls[0]
        assert called_user.id == user.id
        assert called_date == today
        # Summary is the user's current-month audit summary.
        assert hasattr(called_summary, "faltas")


# --------------------------------------------------------------------------- #
# run_reminder_job
# --------------------------------------------------------------------------- #


class TestRunReminderJob:
    async def test_only_audited_users_reminded(self, session_factory, monkeypatch):
        today = date(2026, 6, 23)  # Tuesday
        monkeypatch.setattr(reminder_module, "async_session", session_factory)
        monkeypatch.setattr(
            reminder_module,
            "_today_in_tz",
            lambda tz_name=None: today,
        )

        audited = await _seed_user(session_factory, "audited@x.com", is_audited=True)
        not_audited = await _seed_user(
            session_factory, "plain@x.com", is_audited=False
        )

        notifier = _FakeNotifier()
        await reminder_module.run_reminder_job(notifier)

        reminded_emails = {getattr(c[0], "email") for c in notifier.calls}
        assert "audited@x.com" in reminded_emails
        assert "plain@x.com" not in reminded_emails
        assert len(notifier.calls) == 1

    async def test_swallows_per_user_errors_and_continues(
        self, session_factory, monkeypatch, caplog
    ):
        today = date(2026, 6, 23)
        monkeypatch.setattr(reminder_module, "async_session", session_factory)
        monkeypatch.setattr(
            reminder_module,
            "_today_in_tz",
            lambda tz_name=None: today,
        )

        await _seed_user(session_factory, "boom@x.com", is_audited=True)
        await _seed_user(session_factory, "ok@x.com", is_audited=True)

        notifier = _FakeNotifier()
        notifier.raise_for = "boom@x.com"

        import logging

        with caplog.at_level(logging.ERROR, logger="turbolog.reminder"):
            await reminder_module.run_reminder_job(notifier)

        # boom@x.com raised and was swallowed; ok@x.com still reminded.
        reminded_emails = {getattr(c[0], "email") for c in notifier.calls}
        assert "ok@x.com" in reminded_emails
        # The exception was logged.
        assert any("boom@x.com" in rec.getMessage() or "boom" in rec.getMessage()
                   for rec in caplog.records)

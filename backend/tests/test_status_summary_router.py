"""Black-box tests for GET /api/status/summary.

The summary endpoint returns the authenticated user's current-month audit
counts: {month, expected_days, reported_days, faltas, falta_dates}.

Reuses conftest's app/client fixtures (which patch status_router.async_session
and override get_current_user to the test_user).
"""
import secrets
from datetime import date

import pytest

from app.models.audit_period import AuditPeriod
from app.models.daily_closure import DailyClosure
from app.models.user import User


async def _seed_closure(session_factory, user_id, report_date_str):
    async with session_factory() as s:
        s.add(
            DailyClosure(
                id=secrets.token_hex(16),
                user_id=user_id,
                report_date=report_date_str,
                finalized_at="2026-06-01T00:00:00+00:00",
            )
        )
        await s.commit()


async def _seed_period(session_factory, user_id, started_at: str, ended_at: str | None = None):
    """Insert an AuditPeriod row."""
    async with session_factory() as s:
        s.add(
            AuditPeriod(
                id=secrets.token_hex(16),
                user_id=user_id,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        await s.commit()


async def _seed_other_user(session_factory, email="other@example.com"):
    async with session_factory() as s:
        user = User(
            id=secrets.token_hex(16),
            google_sub=secrets.token_hex(8),
            email=email,
            name="Other",
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


class TestSummaryEndpoint:
    async def test_shape_has_expected_keys(self, client, monkeypatch):
        # Pin "today" so the month is deterministic (June 2026, mid-week).
        from app.services import audit_service as audit_service_mod

        monkeypatch.setattr(audit_service_mod, "_today_in_tz", lambda tz=None: date(2026, 6, 5))

        resp = await client.get("/api/status/summary")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == {
            "month",
            "expected_days",
            "reported_days",
            "faltas",
            "falta_dates",
        }
        assert body["month"] == "2026-06"
        assert isinstance(body["falta_dates"], list)

    async def test_reflects_authenticated_user_own_data(self, client, session_factory, test_user, monkeypatch):
        from app.services import audit_service as audit_service_mod

        monkeypatch.setattr(audit_service_mod, "_today_in_tz", lambda tz=None: date(2026, 6, 5))

        # Seed an audit period covering the full month for test_user.
        await _seed_period(session_factory, test_user.id, "2026-06-01T00:00:00+00:00")
        # Seed a closure for test_user (the authenticated user).
        await _seed_closure(session_factory, test_user.id, "2026-06-02")
        # Seed a closure for ANOTHER user (must NOT affect test_user's counts).
        other = await _seed_other_user(session_factory)
        await _seed_closure(session_factory, other.id, "2026-06-01")
        await _seed_closure(session_factory, other.id, "2026-06-03")

        resp = await client.get("/api/status/summary")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["month"] == "2026-06"
        assert body["expected_days"] == 4  # Mon-Thu Jun 1..4 (today Fri Jun 5 excluded)
        assert body["reported_days"] == 1  # only test_user's single closure
        assert body["faltas"] == 3

    async def test_no_closures_all_faltas(self, client, monkeypatch):
        from app.services import audit_service as audit_service_mod

        monkeypatch.setattr(audit_service_mod, "_today_in_tz", lambda tz=None: date(2026, 6, 5))

        resp = await client.get("/api/status/summary")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reported_days"] == 0
        assert body["faltas"] == body["expected_days"]

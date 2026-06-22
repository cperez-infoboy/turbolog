"""Black-box tests for the "Cerrar día" feature (RED phase).

Covers:
- POST /api/status/finalize happy path (posts comments, creates closure).
- Idempotency: second finalize -> 409, fake add_comment not called again.
- Partial failure: one report's add_comment raises -> 502 with structured body,
  no DailyClosure created, already-posted report keeps its jira_comment_id.
- Retry after partial: remaining report posts -> finalized.
- Lock enforcement: after finalize, POST/PUT/DELETE on that date -> 409.
- Edit-after-send: jira_comment_id set without closure -> PUT/DELETE -> 409.
- JIRA unconfigured: get_jira_client raising surfaces as 500.
- GET shape: {reports, finalized, finalized_at} with jira_comment_id per report.
- Mutex claim-first: pre-seeded closure -> 409 WITHOUT calling add_comment.
- Non-JIRA exception (httpx.TimeoutException) -> 502 failed entry, not 500.
- Bad date payload (non-string / missing) -> 400, not 500.
"""
import secrets

import httpx
import pytest
from sqlalchemy import select, delete

from app.dependencies import get_jira_client
from app.models.daily_closure import DailyClosure
from app.models.status_report import StatusReport
from app.models.task import Task
from app.services.jira_client import JiraError


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _report_payload(task_key: str, date: str, content: str = "did some work") -> dict:
    return {"task_key": task_key, "date": date, "content": content}


async def _seed_report(session_factory, user_id, task_key, date, content="x", jira_comment_id=None):
    """Insert a StatusReport directly via the ORM and return its id."""
    async with session_factory() as s:
        report = StatusReport(
            id=secrets.token_hex(16),
            user_id=user_id,
            task_key=task_key,
            report_date=date,
            content=content,
            jira_comment_id=jira_comment_id,
        )
        s.add(report)
        await s.commit()
        return report.id


async def _seed_task(
    session_factory,
    user_id,
    jira_key,
    summary="some task",
    status="In Progress",
    status_category="indeterminate",
):
    """Insert a Task cache row directly via the ORM and return its id."""
    async with session_factory() as s:
        task = Task(
            user_id=user_id,
            jira_key=jira_key,
            summary=summary,
            status=status,
            status_category=status_category,
        )
        s.add(task)
        await s.commit()
        await s.refresh(task)
        return task.id


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


class TestFinalizeHappyPath:
    async def test_posts_each_report_and_creates_closure(self, client, session_factory, test_user, jira_fake):
        date = "2026-06-22"
        # Two reports with non-empty content.
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="worked on A")
        await _seed_report(session_factory, test_user.id, "PROJ-2", date, content="worked on B")
        jira_fake.add_comment_return_id = "cmt-xyz"

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["finalized"] is True
        assert body["posted"] == 2
        assert "finalized_at" in body and body["finalized_at"]

        # Fake called once per report.
        assert len(jira_fake.call_log) == 2
        posted_keys = {k for (k, _t) in jira_fake.call_log}
        assert posted_keys == {"PROJ-1", "PROJ-2"}

        # DailyClosure row exists.
        async with session_factory() as s:
            result = await s.execute(
                select(DailyClosure).where(
                    DailyClosure.user_id == test_user.id,
                    DailyClosure.report_date == date,
                )
            )
            closure = result.scalar_one_or_none()
            assert closure is not None
            assert closure.finalized_at

        # Reports now carry jira_comment_id.
        async with session_factory() as s:
            result = await s.execute(
                select(StatusReport).where(StatusReport.report_date == date)
            )
            reports = result.scalars().all()
            assert all(r.jira_comment_id == "cmt-xyz" for r in reports)

    async def test_skips_empty_content_reports(self, client, session_factory, test_user, jira_fake):
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="has content")
        await _seed_report(session_factory, test_user.id, "PROJ-2", date, content="   ")

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 200, resp.text
        assert resp.json()["posted"] == 1
        assert len(jira_fake.call_log) == 1
        assert jira_fake.call_log[0][0] == "PROJ-1"

    async def test_skips_already_posted_reports(self, client, session_factory, test_user, jira_fake):
        date = "2026-06-22"
        await _seed_report(
            session_factory, test_user.id, "PROJ-1", date, content="x", jira_comment_id="old-cmt"
        )

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 200, resp.text
        assert resp.json()["posted"] == 0
        # add_comment NOT called because the report already has jira_comment_id.
        assert jira_fake.call_log == []

    async def test_empty_date_returns_400(self, client, jira_fake):
        resp = await client.post("/api/status/finalize", json={"date": "  "})
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


class TestFinalizeIdempotency:
    async def test_second_finalize_is_409_and_does_not_repost(
        self, client, session_factory, test_user, jira_fake
    ):
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")

        first = await client.post("/api/status/finalize", json={"date": date})
        assert first.status_code == 200
        calls_after_first = len(jira_fake.call_log)

        second = await client.post("/api/status/finalize", json={"date": date})
        assert second.status_code == 409
        assert "cerrado" in second.json()["detail"].lower()
        # No additional JIRA calls.
        assert len(jira_fake.call_log) == calls_after_first


# --------------------------------------------------------------------------- #
# Partial failure + retry
# --------------------------------------------------------------------------- #


class TestFinalizePartialFailure:
    async def test_one_failure_returns_502_and_no_closure(
        self, client, session_factory, test_user, jira_fake
    ):
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="first")
        await _seed_report(session_factory, test_user.id, "PROJ-2", date, content="second")

        # PROJ-2 raises; PROJ-1 succeeds with a custom id.
        jira_fake.set_per_key("PROJ-1", lambda k, t: "cmt-ok")
        jira_fake.set_per_key("PROJ-2", JiraError("boom"))

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 502, resp.text
        body = resp.json()
        assert body["finalized"] is False
        assert body["posted"] == 1
        assert len(body["failed"]) == 1
        assert body["failed"][0]["task_key"] == "PROJ-2"
        assert "boom" in body["failed"][0]["error"]

        # NO DailyClosure created.
        async with session_factory() as s:
            result = await s.execute(select(DailyClosure))
            assert result.scalar_one_or_none() is None

        # PROJ-1 retained its jira_comment_id.
        async with session_factory() as s:
            r1 = (
                await s.execute(
                    select(StatusReport).where(StatusReport.task_key == "PROJ-1")
                )
            ).scalar_one()
            assert r1.jira_comment_id == "cmt-ok"
            r2 = (
                await s.execute(
                    select(StatusReport).where(StatusReport.task_key == "PROJ-2")
                )
            ).scalar_one()
            assert r2.jira_comment_id is None

    async def test_retry_after_partial_finalizes_remaining(
        self, client, session_factory, test_user, jira_fake
    ):
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="first")
        await _seed_report(session_factory, test_user.id, "PROJ-2", date, content="second")

        # First attempt: PROJ-2 fails.
        jira_fake.set_per_key("PROJ-2", JiraError("boom"))
        first = await client.post("/api/status/finalize", json={"date": date})
        assert first.status_code == 502

        # Second attempt: both keys now succeed (PROJ-1 is skipped because it
        # already has jira_comment_id; PROJ-2 posts).
        jira_fake.set_per_key("PROJ-2", lambda k, t: "cmt-2")
        jira_fake.set_per_key("PROJ-1", lambda k, t: "SHOULD-NOT-HAPPEN")

        second = await client.post("/api/status/finalize", json={"date": date})
        assert second.status_code == 200, second.text
        body = second.json()
        assert body["finalized"] is True
        assert body["posted"] == 1  # only PROJ-2 reposted

        # Closure now exists.
        async with session_factory() as s:
            result = await s.execute(select(DailyClosure))
            assert result.scalar_one_or_none() is not None


# --------------------------------------------------------------------------- #
# Lock enforcement
# --------------------------------------------------------------------------- #


class TestLockEnforcement:
    async def test_after_finalize_post_upsert_is_409(
        self, client, session_factory, test_user, jira_fake
    ):
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")
        fin = await client.post("/api/status/finalize", json={"date": date})
        assert fin.status_code == 200

        resp = await client.post(
            "/api/status", json=_report_payload("PROJ-9", date, content="new")
        )
        assert resp.status_code == 409
        assert "cerrado" in resp.json()["detail"].lower()

    async def test_after_finalize_put_is_409(self, client, session_factory, test_user, jira_fake):
        date = "2026-06-22"
        rid = await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")
        await client.post("/api/status/finalize", json={"date": date})

        resp = await client.put(f"/api/status/{rid}", json={"content": "edited"})
        assert resp.status_code == 409

    async def test_after_finalize_delete_is_409(self, client, session_factory, test_user, jira_fake):
        date = "2026-06-22"
        rid = await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")
        await client.post("/api/status/finalize", json={"date": date})

        resp = await client.delete(f"/api/status/{rid}")
        assert resp.status_code == 409


class TestEditAfterSend:
    async def test_put_on_report_with_jira_comment_id_is_409(
        self, client, session_factory, test_user, jira_fake
    ):
        date = "2026-06-22"
        rid = await _seed_report(
            session_factory, test_user.id, "PROJ-1", date, content="x", jira_comment_id="cmt"
        )
        # No closure, but the report was already sent.
        resp = await client.put(f"/api/status/{rid}", json={"content": "edited"})
        assert resp.status_code == 409
        assert "jira" in resp.json()["detail"].lower()

    async def test_delete_on_report_with_jira_comment_id_is_409(
        self, client, session_factory, test_user, jira_fake
    ):
        date = "2026-06-22"
        rid = await _seed_report(
            session_factory, test_user.id, "PROJ-1", date, content="x", jira_comment_id="cmt"
        )
        resp = await client.delete(f"/api/status/{rid}")
        assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# JIRA unconfigured
# --------------------------------------------------------------------------- #


class TestJiraUnconfigured:
    async def test_finalize_surfaces_500_when_jira_unconfigured(
        self, client, app, session_factory, test_user
    ):
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")

        from fastapi import HTTPException

        def _raising_jira():
            raise HTTPException(500, "JIRA is not configured on the server")

        app.dependency_overrides[get_jira_client] = _raising_jira

        resp = await client.post("/api/status/finalize", json={"date": date})
        assert resp.status_code == 500


# --------------------------------------------------------------------------- #
# GET shape change
# --------------------------------------------------------------------------- #


class TestGetReportsShape:
    async def test_get_returns_finalized_false_with_null_finalized_at_before_close(
        self, client, session_factory, test_user
    ):
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")

        resp = await client.get("/api/status", params={"date": date})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["finalized"] is False
        assert body["finalized_at"] is None
        assert isinstance(body["reports"], list)
        assert len(body["reports"]) == 1
        assert body["reports"][0]["jira_comment_id"] is None

    async def test_get_returns_finalized_true_after_close(
        self, client, session_factory, test_user, jira_fake
    ):
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")
        await client.post("/api/status/finalize", json={"date": date})

        resp = await client.get("/api/status", params={"date": date})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["finalized"] is True
        assert body["finalized_at"] is not None
        assert body["reports"][0]["jira_comment_id"] == jira_fake.add_comment_return_id

    async def test_today_endpoint_uses_same_shape(
        self, client, session_factory, test_user, monkeypatch
    ):
        # Pin "today" so the /today endpoint resolves deterministically.
        from app.routers import status as status_router
        from datetime import datetime, timezone

        fixed = datetime(2026, 6, 22, tzinfo=timezone.utc)
        monkeypatch.setattr(
            status_router,
            "datetime",
            type(
                "_DT",
                (),
                {
                    "now": staticmethod(lambda tz=None: fixed),
                    "strftime": datetime.strftime,
                },
            ),
        )

        await _seed_report(session_factory, test_user.id, "PROJ-1", "2026-06-22", content="x")

        resp = await client.get("/api/status/today")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "reports" in body and "finalized" in body and "finalized_at" in body


# --------------------------------------------------------------------------- #
# Mutex claim-first (FIX 1)
# --------------------------------------------------------------------------- #


class TestFinalizeMutexClaimFirst:
    async def test_preseeded_closure_returns_409_without_calling_jira(
        self, client, session_factory, test_user, jira_fake
    ):
        """If a DailyClosure already exists, finalize MUST short-circuit at the
        claim step and NEVER call add_comment (no duplicate posts)."""
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")

        # Pre-seed a closure so the unique constraint rejects the claim.
        async with session_factory() as s:
            s.add(
                DailyClosure(
                    id=secrets.token_hex(16),
                    user_id=test_user.id,
                    report_date=date,
                    finalized_at="2026-06-22T00:00:00+00:00",
                )
            )
            await s.commit()

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 409, resp.text
        assert "cerrado" in resp.json()["detail"].lower()
        # CRITICAL: add_comment was never called (no duplicate posts possible).
        assert jira_fake.call_log == []


# --------------------------------------------------------------------------- #
# Non-JIRA exception broadened handling (FIX 2)
# --------------------------------------------------------------------------- #


class TestFinalizeNonJiraException:
    async def test_timeout_exception_returns_502_not_500(
        self, client, session_factory, test_user, jira_fake
    ):
        """An httpx.TimeoutException (not a JiraError) must be captured into
        `failed` and return 502, NOT escape as a 500."""
        date = "2026-06-22"
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="x")
        await _seed_report(session_factory, test_user.id, "PROJ-2", date, content="y")

        # PROJ-1 succeeds, PROJ-2 raises a non-JIRA network error.
        jira_fake.set_per_key("PROJ-1", lambda k, t: "cmt-1")
        jira_fake.set_per_key("PROJ-2", httpx.TimeoutException("timeout"))

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 502, resp.text
        body = resp.json()
        assert body["finalized"] is False
        assert body["posted"] == 1
        assert len(body["failed"]) == 1
        assert body["failed"][0]["task_key"] == "PROJ-2"

        # Claim was deleted (day must NOT stay locked on failure).
        async with session_factory() as s:
            result = await s.execute(select(DailyClosure))
            assert result.scalar_one_or_none() is None


# --------------------------------------------------------------------------- #
# Bad date payload -> 400 (FIX 3)
# --------------------------------------------------------------------------- #


class TestFinalizeBadDatePayload:
    async def test_non_string_date_returns_400(self, client, jira_fake):
        resp = await client.post("/api/status/finalize", json={"date": 123})
        assert resp.status_code == 400, resp.text

    async def test_missing_date_returns_400(self, client, jira_fake):
        resp = await client.post("/api/status/finalize", json={})
        assert resp.status_code == 400, resp.text

    async def test_null_date_returns_400(self, client, jira_fake):
        resp = await client.post("/api/status/finalize", json={"date": None})
        assert resp.status_code == 400, resp.text


# --------------------------------------------------------------------------- #
# Status-coverage validation (422 rule)
# --------------------------------------------------------------------------- #


class TestFinalizeStatusCoverage:
    async def test_missing_in_progress_status_returns_422(
        self, client, session_factory, test_user, jira_fake
    ):
        """In-progress tasks without a non-empty status report block finalize
        with 422, BEFORE the mutex is claimed or JIRA is called."""
        date = "2026-06-22"
        await _seed_task(session_factory, test_user.id, "PROJ-1", summary="Task one")
        await _seed_task(session_factory, test_user.id, "PROJ-2", summary="Task two")
        # Only PROJ-1 has a report; PROJ-2 is missing.
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="did A")

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["finalized"] is False
        assert isinstance(body["missing"], list)
        assert len(body["missing"]) == 1
        missing_entry = body["missing"][0]
        assert missing_entry["task_key"] == "PROJ-2"
        assert missing_entry["task_summary"] == "Task two"

        # No closure row created.
        async with session_factory() as s:
            result = await s.execute(select(DailyClosure))
            assert result.scalar_one_or_none() is None

        # JIRA never called.
        assert jira_fake.call_log == []

    async def test_all_in_progress_have_status_finalizes_200(
        self, client, session_factory, test_user, jira_fake
    ):
        """When every in-progress task has a non-empty status, finalize proceeds."""
        date = "2026-06-22"
        await _seed_task(session_factory, test_user.id, "PROJ-1", summary="Task one")
        await _seed_task(session_factory, test_user.id, "PROJ-2", summary="Task two")
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="did A")
        await _seed_report(session_factory, test_user.id, "PROJ-2", date, content="did B")

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["finalized"] is True
        assert body["posted"] == 2

        async with session_factory() as s:
            result = await s.execute(
                select(DailyClosure).where(
                    DailyClosure.user_id == test_user.id,
                    DailyClosure.report_date == date,
                )
            )
            assert result.scalar_one_or_none() is not None

    async def test_zero_in_progress_tasks_passes_vacuously(
        self, client, session_factory, test_user, jira_fake
    ):
        """A to-do task (status_category='new') does not require a status; the
        coverage rule passes vacuously when there are no in-progress tasks."""
        date = "2026-06-22"
        await _seed_task(
            session_factory,
            test_user.id,
            "PROJ-1",
            summary="To-do task",
            status_category="new",
        )
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="planning")

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["finalized"] is True

    async def test_409_precedence_over_422(
        self, client, session_factory, test_user, jira_fake
    ):
        """An already-closed day returns 409 even if in-progress tasks lack a
        status report — the closure check wins over the coverage check."""
        date = "2026-06-22"
        # In-progress task with NO status report (would trigger 422).
        await _seed_task(session_factory, test_user.id, "PROJ-1", summary="Task one")
        # Pre-existing closure (would trigger 409).
        async with session_factory() as s:
            s.add(
                DailyClosure(
                    id=secrets.token_hex(16),
                    user_id=test_user.id,
                    report_date=date,
                    finalized_at="2026-06-22T00:00:00+00:00",
                )
            )
            await s.commit()

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 409, resp.text
        assert "cerrado" in resp.json()["detail"].lower()
        # JIRA never called.
        assert jira_fake.call_log == []

    async def test_422_lists_all_missing_tasks(
        self, client, session_factory, test_user, jira_fake
    ):
        """If multiple in-progress tasks lack statuses, all appear in `missing`."""
        date = "2026-06-22"
        await _seed_task(session_factory, test_user.id, "PROJ-1", summary="Task one")
        await _seed_task(session_factory, test_user.id, "PROJ-2", summary="Task two")
        await _seed_task(session_factory, test_user.id, "PROJ-3", summary="Task three")
        # Only PROJ-1 has a report.
        await _seed_report(session_factory, test_user.id, "PROJ-1", date, content="did A")

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 422, resp.text
        body = resp.json()
        missing_keys = {entry["task_key"] for entry in body["missing"]}
        assert missing_keys == {"PROJ-2", "PROJ-3"}
        # Each entry carries its summary.
        for entry in body["missing"]:
            assert entry["task_summary"]

    async def test_empty_content_report_does_not_count_as_covered(
        self, client, session_factory, test_user, jira_fake
    ):
        """A report whose content is whitespace-only does NOT satisfy coverage."""
        date = "2026-06-22"
        await _seed_task(session_factory, test_user.id, "PROJ-1", summary="Task one")
        # Report exists but content is whitespace.
        await _seed_report(
            session_factory, test_user.id, "PROJ-1", date, content="   "
        )

        resp = await client.post("/api/status/finalize", json={"date": date})

        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["finalized"] is False
        assert len(body["missing"]) == 1
        assert body["missing"][0]["task_key"] == "PROJ-1"
        assert jira_fake.call_log == []

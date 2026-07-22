"""Monthly audit computation service (pure logic + DB queries).

Computes, for a given user/month:
- expected weekdays (Mon-Fri) up to "today" (no feriados in v1)
- reported days (rows in daily_closures for that user/month)
- faltas = expected - reported, with the specific falta dates

`today` is injectable for deterministic tests; production derives it from
``settings.AUDIT_TIMEZONE`` via :func:`_today_in_tz`.

``report_date`` in the DB is a free-form ISO string ("YYYY-MM-DD"). Every read
parses defensively with :func:`date.fromisoformat`; malformed rows are skipped
and logged, never raised.

Result types are pydantic ``BaseModel`` (fastapi already depends on pydantic),
matching the repo's use of pydantic for serializable shapes.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit_period import AuditPeriod
from app.models.daily_closure import DailyClosure
from app.models.status_report import StatusReport
from app.models.task import Task
from app.models.user import User

logger = logging.getLogger("turbolog.audit")

# SQLAlchemy async session factory / session-like objects expose an async context
# manager. Both the real ``async_sessionmaker`` and the test fixtures produce
# objects usable with ``async with ... as session``. We type loosely to accept
# either a factory or an already-open session.
SessionFactory = Any


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #


try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - pydantic is a fastapi hard dep
    BaseModel = object  # type: ignore[assignment,misc]


class MonthAudit(BaseModel):
    """Per-user, per-month audit for a single user (no email)."""

    user_id: str
    expected_days: int
    reported_days: int
    faltas: int
    falta_dates: list[date]


class UserMonthAudit(BaseModel):
    """Per-user audit entry as returned by the admin monthly report (with email)."""

    user_id: str
    user_email: str
    expected_days: int
    reported_days: int
    faltas: int
    falta_dates: list[date]


class UserSummary(BaseModel):
    """The authenticated user's own current-month summary (no id/email)."""

    month: str  # "YYYY-MM"
    expected_days: int
    reported_days: int
    faltas: int
    falta_dates: list[date]


class StatusReportEntry(BaseModel):
    """One status row a user reported: content + task + JIRA-posted flag."""

    report_date: str  # ISO string — lexicographic sort matches chronological
    task_key: str
    task_summary: str | None  # None when the task no longer exists in JIRA
    content: str
    posted_to_jira: bool  # jira_comment_id is not None
    updated_at: str


class UserMonthStatuses(BaseModel):
    """All status reports a user filed in a month (admin detailed view)."""

    user_id: str
    user_email: str
    user_name: str
    reports: list[StatusReportEntry]


# --------------------------------------------------------------------------- #
# Calendar helpers (pure)
# --------------------------------------------------------------------------- #


def _today_in_tz(tz_name: str | None = None) -> date:
    """Today's date in the configured audit timezone."""
    return datetime.now(ZoneInfo(tz_name or settings.AUDIT_TIMEZONE)).date()


def expected_weekdays(start: date, end: date, today: date) -> list[date]:
    """Mon-Fri dates in ``[start, end]`` inclusive, with each date ``<= today``.

    Pure calendar walk; no feriados/excepciones in v1. Future weekdays beyond
    ``today`` are excluded (they cannot be "faltas" yet).
    """
    result: list[date] = []
    if start > end:
        return result
    # Walk day by day using ordinal arithmetic (avoids timedelta edge cases).
    cur = start
    while cur <= end:
        if cur <= today and cur.weekday() < 5:  # Mon=0 .. Fri=4
            result.append(cur)
        cur = date.fromordinal(cur.toordinal() + 1)
    return result


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """First and last day of the given month."""
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return first, last


# --------------------------------------------------------------------------- #
# DB queries
# --------------------------------------------------------------------------- #


async def fetch_reported_dates(
    session_factory: SessionFactory,
    user_id: str,
    start: date,
    end: date,
) -> set[date]:
    """Return the set of reported dates for ``user_id`` in ``[start, end]``.

    Queries ``daily_closures.report_date`` (a String ISO column) and parses each
    row defensively: malformed strings are skipped and logged, never raised.
    """
    start_str = start.isoformat()
    end_str = end.isoformat()

    async with session_factory() as session:
        result = await session.execute(
            select(DailyClosure.report_date).where(
                DailyClosure.user_id == user_id,
                DailyClosure.report_date >= start_str,
                DailyClosure.report_date <= end_str,
            )
        )
        rows = result.scalars().all()

    reported: set[date] = set()
    for raw in rows:
        if raw is None:
            continue
        try:
            reported.add(date.fromisoformat(raw))
        except (ValueError, TypeError):
            logger.warning(
                "Malformed report_date %r for user_id=%s skipped", raw, user_id
            )
            continue
    return reported


async def fetch_user_month_statuses(
    session_factory: SessionFactory,
    user_id: str,
    year: int,
    month: int,
) -> list[StatusReportEntry]:
    """Return the status reports a user filed in a given month, enriched with
    each task's summary and whether it was posted to JIRA.

    No audit-period gating — this shows everything the user reported in the
    month regardless of whether the audit window was open.
    """
    month_prefix = f"{year}-{month:02d}-"
    async with session_factory() as session:
        result = await session.execute(
            select(StatusReport).where(
                StatusReport.user_id == user_id,
                StatusReport.report_date.like(f"{month_prefix}%"),
            ).order_by(StatusReport.report_date, StatusReport.task_key)
        )
        reports = result.scalars().all()

        task_keys = [r.task_key for r in reports]
        summaries: dict[str, str] = {}
        if task_keys:
            task_result = await session.execute(
                select(Task).where(
                    Task.user_id == user_id,
                    Task.jira_key.in_(task_keys),
                )
            )
            for task in task_result.scalars().all():
                summaries[task.jira_key] = task.summary

    return [
        StatusReportEntry(
            report_date=r.report_date,
            task_key=r.task_key,
            task_summary=summaries.get(r.task_key),
            content=r.content,
            posted_to_jira=r.jira_comment_id is not None,
            updated_at=r.updated_at,
        )
        for r in reports
    ]


async def fetch_audit_periods(
    session_factory: SessionFactory,
    user_id: str,
    start: date,
    end: date,
) -> list[tuple[date, date]]:
    """Return audit periods overlapping ``[start, end]`` for ``user_id``.

    Each tuple is ``(period_start, period_end)`` where ``period_end`` is
    ``today`` if the period is still open (``ended_at IS NULL``).
    """
    start_str = start.isoformat()
    # A period overlaps [start, end] if it started before end+1 AND
    # (it hasn't ended OR it ended on or after start).
    end_plus1 = date.fromordinal(end.toordinal() + 1).isoformat()

    async with session_factory() as session:
        result = await session.execute(
            select(AuditPeriod).where(
                AuditPeriod.user_id == user_id,
                AuditPeriod.started_at < end_plus1,
                (AuditPeriod.ended_at.is_(None)) | (AuditPeriod.ended_at >= start_str),
            )
        )
        rows = result.scalars().all()

    periods: list[tuple[date, date]] = []
    for row in rows:
        try:
            p_start = date.fromisoformat(row.started_at[:10])
        except (ValueError, TypeError):
            logger.warning(
                "Malformed started_at %r for audit_period %s skipped",
                row.started_at, row.id,
            )
            continue
        if row.ended_at is not None:
            try:
                p_end = date.fromisoformat(row.ended_at[:10])
            except (ValueError, TypeError):
                logger.warning(
                    "Malformed ended_at %r for audit_period %s skipped",
                    row.ended_at, row.id,
                )
                continue
        else:
            # Open period — extends through today (capped by caller).
            p_end = end
        periods.append((p_start, p_end))
    return periods


# --------------------------------------------------------------------------- #
# Audit computations
# --------------------------------------------------------------------------- #


async def compute_month_audit(
    session_factory: SessionFactory,
    user_id: str,
    year: int,
    month: int,
    *,
    today: date | None = None,
    audit_periods: list[tuple[date, date]] | None = None,
) -> MonthAudit:
    """Compute the audit for a single user in a single month.

    If *audit_periods* is provided (list of ``(period_start, period_end)``),
    expected weekdays are counted only within those ranges.  If ``None``,
    periods are fetched from the DB so callers like the reminder job and
    status summary work without changes.
    """
    if today is None:
        today = _today_in_tz()

    month_start, month_end = _month_bounds(year, month)

    # Today is still in progress — only fully-elapsed days can be faltas.
    last_elapsed = date.fromordinal(today.toordinal() - 1)

    # Fetch periods if the caller didn't provide them.
    if audit_periods is None:
        audit_periods = await fetch_audit_periods(
            session_factory, user_id, month_start, month_end
        )

    # Collect expected weekdays across all active periods.
    expected: list[date] = []
    for p_start, p_end in audit_periods:
        range_start = max(p_start, month_start)
        range_end = min(p_end, month_end, last_elapsed)
        expected.extend(expected_weekdays(range_start, range_end, last_elapsed))
    expected = sorted(set(expected))

    reported = await fetch_reported_dates(session_factory, user_id, month_start, month_end)

    reported_dates = sorted(d for d in expected if d in reported)
    falta_dates = sorted(d for d in expected if d not in reported)

    return MonthAudit(
        user_id=user_id,
        expected_days=len(expected),
        reported_days=len(reported_dates),
        faltas=len(falta_dates),
        falta_dates=falta_dates,
    )


async def compute_user_month_summary(
    session_factory: SessionFactory,
    user_id: str,
    *,
    today: date | None = None,
) -> UserSummary:
    """The authenticated user's own current-month summary."""
    if today is None:
        today = _today_in_tz()

    year, month = today.year, today.month
    audit = await compute_month_audit(
        session_factory, user_id, year, month, today=today
    )
    return UserSummary(
        month=f"{year:04d}-{month:02d}",
        expected_days=audit.expected_days,
        reported_days=audit.reported_days,
        faltas=audit.faltas,
        falta_dates=audit.falta_dates,
    )


async def compute_audit_for_all_users(
    session_factory: SessionFactory,
    year: int,
    month: int,
    *,
    today: date | None = None,
) -> list[UserMonthAudit]:
    """Compute the monthly audit for every user with ``is_audited == True``.

    Pre-fetches all audit periods for the month in a single query (avoids
    N+1), then passes per-user periods to ``compute_month_audit``.
    """
    if today is None:
        today = _today_in_tz()

    month_start, month_end = _month_bounds(year, month)

    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.is_audited.is_(True))
        )
        users = result.scalars().all()

    # Pre-fetch all audit periods for the relevant month in one query.
    periods_by_user: dict[str, list[tuple[date, date]]] = {}
    if users:
        user_ids = [u.id for u in users]
        async with session_factory() as session:
            result = await session.execute(
                select(AuditPeriod).where(
                    AuditPeriod.user_id.in_(user_ids),
                    AuditPeriod.started_at < date.fromordinal(
                        month_end.toordinal() + 1
                    ).isoformat(),
                    (AuditPeriod.ended_at.is_(None))
                    | (AuditPeriod.ended_at >= month_start.isoformat()),
                )
            )
            rows = result.scalars().all()

        for row in rows:
            try:
                p_start = date.fromisoformat(row.started_at[:10])
            except (ValueError, TypeError):
                continue
            if row.ended_at is not None:
                try:
                    p_end = date.fromisoformat(row.ended_at[:10])
                except (ValueError, TypeError):
                    continue
            else:
                p_end = month_end
            periods_by_user.setdefault(row.user_id, []).append((p_start, p_end))

    entries: list[UserMonthAudit] = []
    for user in users:
        periods = periods_by_user.get(user.id, [])
        audit = await compute_month_audit(
            session_factory, user.id, year, month, today=today,
            audit_periods=periods,
        )
        entries.append(
            UserMonthAudit(
                user_id=user.id,
                user_email=user.email,
                expected_days=audit.expected_days,
                reported_days=audit.reported_days,
                faltas=audit.faltas,
                falta_dates=audit.falta_dates,
            )
        )
    return entries

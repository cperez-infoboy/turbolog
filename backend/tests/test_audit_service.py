"""Tests for the audit computation service (pure logic + DB queries).

Covers:
- expected_weekdays: Mon-Fri only, excludes future dates > today, single-day,
  full month, boundary at month end.
- fetch_reported_dates: seeded closures -> correct set; malformed rows skipped.
- compute_month_audit: matrix expected=5/closures=3 -> reported 3, faltas 2;
  mid-month (today mid-range) excludes future weekdays; empty user.
- compute_month_audit with audit_periods: periods restrict expected days.
- compute_user_month_summary: determinism via injected today; month label.
- compute_audit_for_all_users: only is_audited=True users appear; email populated.
"""
import secrets
from datetime import date

import pytest

from app.models.audit_period import AuditPeriod
from app.models.daily_closure import DailyClosure
from app.models.user import User
from app.services.audit_service import (
    MonthAudit,
    UserMonthAudit,
    UserSummary,
    compute_audit_for_all_users,
    compute_month_audit,
    compute_user_month_summary,
    expected_weekdays,
    fetch_audit_periods,
    fetch_reported_dates,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(session_factory, *, email="u@example.com", is_audited=False, is_admin=False):
    async with session_factory() as s:
        user = User(
            id=secrets.token_hex(16),
            google_sub=secrets.token_hex(8),
            email=email,
            name="U",
            is_audited=is_audited,
            is_admin=is_admin,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _seed_closure(session_factory, user_id, report_date_str):
    async with session_factory() as s:
        s.add(
            DailyClosure(
                id=secrets.token_hex(16),
                user_id=user_id,
                report_date=report_date_str,
                finalized_at="2026-01-01T00:00:00+00:00",
            )
        )
        await s.commit()


async def _seed_raw_row(session_factory, user_id, report_date_str, *, finalized_at="x"):
    """Insert a DailyClosure row bypassing ORM validation for malformed dates."""
    async with session_factory() as s:
        s.add(
            DailyClosure(
                id=secrets.token_hex(16),
                user_id=user_id,
                report_date=report_date_str,
                finalized_at=finalized_at,
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


# --------------------------------------------------------------------------- #
# expected_weekdays
# --------------------------------------------------------------------------- #


class TestExpectedWeekdays:
    def test_mon_to_fri_only_no_weekend(self):
        # 2026-06-01 is Monday; 2026-06-07 is Sunday.
        days = expected_weekdays(date(2026, 6, 1), date(2026, 6, 7), date(2026, 6, 7))
        weekday_iso = [d.weekday() for d in days]
        assert all(w < 5 for w in weekday_iso)  # Mon-Fri == 0..4
        # 5 weekdays, no Sat/Sun.
        assert len(days) == 5
        assert date(2026, 6, 6) not in days  # Sat
        assert date(2026, 6, 7) not in days  # Sun

    def test_excludes_future_dates_beyond_today(self):
        # Range covers Mon-Fri of week, but today is Wednesday mid-week.
        days = expected_weekdays(date(2026, 6, 1), date(2026, 6, 5), date(2026, 6, 3))
        # Only Mon(1), Tue(2), Wed(3) -> Thu(4) and Fri(5) excluded (> today).
        assert days == [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)]

    def test_single_day_range(self):
        # Single Monday.
        days = expected_weekdays(date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 1))
        assert days == [date(2026, 6, 1)]

    def test_single_day_that_is_weekend_returns_empty(self):
        # Single Saturday.
        days = expected_weekdays(date(2026, 6, 6), date(2026, 6, 6), date(2026, 6, 6))
        assert days == []

    def test_full_month_boundaries(self):
        # January 2026: Jan 1 is Thursday, Jan 31 is Saturday.
        # Weekdays in Jan 2026 = 22 (Mon-Fri, excluding weekends).
        days = expected_weekdays(date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 31))
        assert all(d.month == 1 for d in days)
        assert all(d.weekday() < 5 for d in days)
        # First weekday is Thu Jan 1; last is Fri Jan 30 (Sat 31 excluded).
        assert days[0] == date(2026, 1, 1)
        assert days[-1] == date(2026, 1, 30)
        assert len(days) == 22

    def test_today_inclusive(self):
        # today == Friday, must be included.
        days = expected_weekdays(date(2026, 6, 1), date(2026, 6, 5), date(2026, 6, 5))
        assert date(2026, 6, 5) in days


# --------------------------------------------------------------------------- #
# fetch_reported_dates
# --------------------------------------------------------------------------- #


class TestFetchReportedDates:
    async def test_returns_set_of_reported_dates(self, session_factory):
        user = await _seed_user(session_factory)
        await _seed_closure(session_factory, user.id, "2026-06-01")
        await _seed_closure(session_factory, user.id, "2026-06-03")

        result = await fetch_reported_dates(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result == {date(2026, 6, 1), date(2026, 6, 3)}

    async def test_filters_outside_range(self, session_factory):
        user = await _seed_user(session_factory)
        await _seed_closure(session_factory, user.id, "2026-05-30")  # before
        await _seed_closure(session_factory, user.id, "2026-06-02")  # in
        await _seed_closure(session_factory, user.id, "2026-07-01")  # after

        result = await fetch_reported_dates(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result == {date(2026, 6, 2)}

    async def test_malformed_row_skipped_not_raised(self, session_factory):
        user = await _seed_user(session_factory)
        await _seed_closure(session_factory, user.id, "2026-06-02")
        # Malformed ISO string.
        await _seed_raw_row(session_factory, user.id, "not-a-date")

        result = await fetch_reported_dates(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        # Valid row kept, malformed skipped (no crash).
        assert result == {date(2026, 6, 2)}

    async def test_user_with_no_closures_returns_empty(self, session_factory):
        user = await _seed_user(session_factory)
        result = await fetch_reported_dates(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert result == set()


# --------------------------------------------------------------------------- #
# compute_month_audit
# --------------------------------------------------------------------------- #


class TestComputeMonthAudit:
    async def test_matrix_three_reported_two_faltas(self, session_factory):
        """5 weekdays in the first week, today=Fri Jun 5 → expected Mon-Thu (4),
        reported 3, faltas 1 (today is in-progress, never a falta)."""
        user = await _seed_user(session_factory)
        # Full-month audit period (the common case).
        await _seed_period(session_factory, user.id, "2026-06-01T00:00:00+00:00")
        # June 2026: 1(Mon),2(Tue),3(Wed),4(Thu),5(Fri) are the first week.
        await _seed_closure(session_factory, user.id, "2026-06-01")
        await _seed_closure(session_factory, user.id, "2026-06-02")
        await _seed_closure(session_factory, user.id, "2026-06-04")

        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6, today=date(2026, 6, 5)
        )

        assert isinstance(audit, MonthAudit)
        assert audit.user_id == user.id
        # Today (Fri Jun 5) is in-progress → excluded. Expected = Mon-Thu = 4.
        assert audit.expected_days == 4
        assert audit.reported_days == 3
        assert audit.faltas == 1
        assert audit.falta_dates == [date(2026, 6, 3)]

    async def test_today_in_progress_never_a_falta(self, session_factory):
        """The current day is never counted as a falta even without a closure:
        it can still be closed before end of day."""
        user = await _seed_user(session_factory)
        await _seed_period(session_factory, user.id, "2026-06-01T00:00:00+00:00")
        # Only Mon and Tue have closures; today is Wed Jun 3 (no closure yet).
        await _seed_closure(session_factory, user.id, "2026-06-01")
        await _seed_closure(session_factory, user.id, "2026-06-02")

        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6, today=date(2026, 6, 3)
        )
        # Expected = Mon, Tue (Wed today excluded). Both reported → 0 faltas.
        assert audit.expected_days == 2
        assert audit.reported_days == 2
        assert audit.faltas == 0
        assert date(2026, 6, 3) not in audit.falta_dates

    async def test_mid_month_excludes_future_weekdays(self, session_factory):
        user = await _seed_user(session_factory)
        await _seed_period(session_factory, user.id, "2026-06-01T00:00:00+00:00")
        # Report the whole first week.
        await _seed_closure(session_factory, user.id, "2026-06-01")
        await _seed_closure(session_factory, user.id, "2026-06-02")
        await _seed_closure(session_factory, user.id, "2026-06-03")

        # today = Wed Jun 3 (mid-month). Tue Jun 2 is the last elapsed day:
        # Wed (today) is excluded, Thu/Fri are future.
        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6, today=date(2026, 6, 3)
        )
        assert audit.expected_days == 2  # Mon, Tue
        assert audit.reported_days == 2
        assert audit.faltas == 0
        assert audit.falta_dates == []

    async def test_user_with_no_closures_all_faltas(self, session_factory):
        user = await _seed_user(session_factory)
        await _seed_period(session_factory, user.id, "2026-06-01T00:00:00+00:00")
        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6, today=date(2026, 6, 5)
        )
        # Today (Fri Jun 5) excluded → expected Mon-Thu = 4, all faltas.
        assert audit.expected_days == 4
        assert audit.reported_days == 0
        assert audit.faltas == 4
        assert audit.falta_dates == [
            date(2026, 6, 1),
            date(2026, 6, 2),
            date(2026, 6, 3),
            date(2026, 6, 4),
        ]


# --------------------------------------------------------------------------- #
# compute_user_month_summary
# --------------------------------------------------------------------------- #


class TestComputeUserMonthSummary:
    async def test_month_label_and_counts(self, session_factory):
        user = await _seed_user(session_factory)
        await _seed_period(session_factory, user.id, "2026-06-01T00:00:00+00:00")
        await _seed_closure(session_factory, user.id, "2026-06-02")

        summary = await compute_user_month_summary(
            session_factory, user.id, today=date(2026, 6, 5)
        )

        assert isinstance(summary, UserSummary)
        assert summary.month == "2026-06"
        # Today (Fri Jun 5) excluded → expected Mon-Thu = 4.
        assert summary.expected_days == 4
        assert summary.reported_days == 1
        assert summary.faltas == 3


# --------------------------------------------------------------------------- #
# compute_audit_for_all_users
# --------------------------------------------------------------------------- #


class TestComputeAuditForAllUsers:
    async def test_only_audited_users_appear_with_email(self, session_factory):
        audited = await _seed_user(session_factory, email="audited@example.com", is_audited=True)
        not_audited = await _seed_user(session_factory, email="other@example.com", is_audited=False)

        await _seed_period(session_factory, audited.id, "2026-06-01T00:00:00+00:00")
        await _seed_closure(session_factory, audited.id, "2026-06-02")

        results = await compute_audit_for_all_users(
            session_factory, 2026, 6, today=date(2026, 6, 5)
        )

        assert isinstance(results, list)
        assert len(results) == 1
        entry = results[0]
        assert isinstance(entry, UserMonthAudit)
        assert entry.user_id == audited.id
        assert entry.user_email == "audited@example.com"
        assert entry.reported_days == 1
        # The non-audited user must NOT appear.
        assert all(r.user_id != not_audited.id for r in results)

    async def test_periods_restrict_expected_days(self, session_factory):
        """Audit periods limit which days count as expected."""
        user = await _seed_user(session_factory, email="p@example.com", is_audited=True)
        # Period: Jun 8-14 only (not the full month).
        await _seed_period(
            session_factory, user.id,
            started_at="2026-06-08T00:00:00+00:00",
            ended_at="2026-06-14T00:00:00+00:00",
        )

        results = await compute_audit_for_all_users(
            session_factory, 2026, 6, today=date(2026, 6, 25)
        )

        assert len(results) == 1
        entry = results[0]
        # Jun 8(Mon)-14(Sun): weekdays are Mon-Fri = 8,9,10,11,12 → 5 days.
        assert entry.expected_days == 5
        assert entry.reported_days == 0
        assert entry.faltas == 5


# --------------------------------------------------------------------------- #
# fetch_audit_periods
# --------------------------------------------------------------------------- #


class TestFetchAuditPeriods:
    async def test_returns_periods_overlapping_month(self, session_factory):
        user = await _seed_user(session_factory)
        # Period fully within June.
        await _seed_period(
            session_factory, user.id,
            started_at="2026-06-08T00:00:00+00:00",
            ended_at="2026-06-14T00:00:00+00:00",
        )

        periods = await fetch_audit_periods(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert len(periods) == 1
        assert periods[0] == (date(2026, 6, 8), date(2026, 6, 14))

    async def test_open_period_uses_end_as_period_end(self, session_factory):
        user = await _seed_user(session_factory)
        # Open period (ended_at=None).
        await _seed_period(
            session_factory, user.id,
            started_at="2026-06-20T00:00:00+00:00",
        )

        periods = await fetch_audit_periods(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert len(periods) == 1
        # Open period → ended_at defaults to the query end date.
        assert periods[0] == (date(2026, 6, 20), date(2026, 6, 30))

    async def test_period_starting_before_month_is_clamped(self, session_factory):
        user = await _seed_user(session_factory)
        # Period starts in May, ends in June.
        await _seed_period(
            session_factory, user.id,
            started_at="2026-05-25T00:00:00+00:00",
            ended_at="2026-06-05T00:00:00+00:00",
        )

        periods = await fetch_audit_periods(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert len(periods) == 1
        # started_at is the raw value; clamping happens in compute_month_audit.
        assert periods[0][0] == date(2026, 5, 25)
        assert periods[0][1] == date(2026, 6, 5)

    async def test_no_periods_returns_empty(self, session_factory):
        user = await _seed_user(session_factory)
        periods = await fetch_audit_periods(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert periods == []

    async def test_multiple_periods_returned(self, session_factory):
        user = await _seed_user(session_factory)
        await _seed_period(
            session_factory, user.id,
            started_at="2026-06-01T00:00:00+00:00",
            ended_at="2026-06-07T00:00:00+00:00",
        )
        await _seed_period(
            session_factory, user.id,
            started_at="2026-06-15T00:00:00+00:00",
            ended_at="2026-06-21T00:00:00+00:00",
        )

        periods = await fetch_audit_periods(
            session_factory, user.id, date(2026, 6, 1), date(2026, 6, 30)
        )
        assert len(periods) == 2


# --------------------------------------------------------------------------- #
# compute_month_audit with periods
# --------------------------------------------------------------------------- #


class TestComputeMonthAuditWithPeriods:
    async def test_single_period_mid_month(self, session_factory):
        """Expected days only from the period, not the full month."""
        user = await _seed_user(session_factory)
        # Period: Jun 8 (Mon) - Jun 14 (Sun).
        periods = [(date(2026, 6, 8), date(2026, 6, 14))]

        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6,
            today=date(2026, 6, 25),
            audit_periods=periods,
        )
        # Weekdays in Jun 8-14: Mon(8), Tue(9), Wed(10), Thu(11), Fri(12) = 5.
        assert audit.expected_days == 5
        assert audit.faltas == 5

    async def test_two_periods_with_gap(self, session_factory):
        """Gap between periods is not counted as faltas."""
        user = await _seed_user(session_factory)
        # Period 1: Jun 1-5, Period 2: Jun 15-19.
        periods = [
            (date(2026, 6, 1), date(2026, 6, 5)),
            (date(2026, 6, 15), date(2026, 6, 19)),
        ]

        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6,
            today=date(2026, 6, 25),
            audit_periods=periods,
        )
        # Jun 1-5: 5 weekdays. Jun 15-19: Mon-Fri = 5 weekdays. Total = 10.
        assert audit.expected_days == 10
        # Jun 6-14 gap NOT counted.
        assert audit.faltas == 10

    async def test_period_started_before_month(self, session_factory):
        """Period starting before the month → expected from day 1 of month."""
        user = await _seed_user(session_factory)
        # Period: May 25 - Jun 5 (open-ended from before the month).
        periods = [(date(2026, 5, 25), date(2026, 6, 5))]

        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6,
            today=date(2026, 6, 25),
            audit_periods=periods,
        )
        # Clamped to Jun 1-5: Mon-Fri = 5 weekdays.
        assert audit.expected_days == 5

    async def test_no_periods_means_zero_expected(self, session_factory):
        """User with no audit periods → expected = 0."""
        user = await _seed_user(session_factory)

        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6,
            today=date(2026, 6, 25),
            audit_periods=[],
        )
        assert audit.expected_days == 0
        assert audit.faltas == 0
        assert audit.falta_dates == []

    async def test_periods_fetched_internally_when_not_provided(self, session_factory):
        """compute_month_audit fetches periods from DB when audit_periods=None."""
        user = await _seed_user(session_factory)
        await _seed_period(
            session_factory, user.id,
            started_at="2026-06-08T00:00:00+00:00",
            ended_at="2026-06-14T00:00:00+00:00",
        )

        # Call without audit_periods → should fetch internally.
        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6,
            today=date(2026, 6, 25),
        )
        assert audit.expected_days == 5

    async def test_open_period_extends_through_today(self, session_factory):
        """Open period (ended_at=None) counts up to the last elapsed day
        (today itself is in-progress and excluded)."""
        user = await _seed_user(session_factory)
        await _seed_period(
            session_factory, user.id,
            started_at="2026-06-01T00:00:00+00:00",
            # No ended_at → open period.
        )

        audit = await compute_month_audit(
            session_factory, user.id, 2026, 6,
            today=date(2026, 6, 5),
        )
        # First week Mon-Thu = 4 (Fri Jun 5 is today → excluded).
        assert audit.expected_days == 4

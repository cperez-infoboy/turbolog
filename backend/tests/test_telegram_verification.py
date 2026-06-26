"""Tests for the Telegram verification code store (RED phase).

The store is an in-memory dict with TTL. Codes are 6-digit strings,
one per user (creating a new code replaces any previous one).
"""
from datetime import datetime, timezone, timedelta

import pytest

from app.services.telegram_verification import VerificationStore


class TestCreateCode:
    async def test_returns_six_digit_string(self):
        store = VerificationStore(ttl_seconds=300)
        code = store.create_code("user-1")
        assert len(code) == 6
        assert code.isdigit()

    async def test_replaces_previous_code_for_same_user(self):
        store = VerificationStore(ttl_seconds=300)
        code1 = store.create_code("user-1")
        code2 = store.create_code("user-1")
        # Both are valid 6-digit codes.
        assert len(code2) == 6
        # But only code2 is stored — code1 was evicted.
        result = store.consume_code(code1)
        assert result is None
        result = store.consume_code(code2)
        assert result == "user-1"

    async def test_different_users_get_independent_codes(self):
        store = VerificationStore(ttl_seconds=300)
        code_a = store.create_code("user-a")
        code_b = store.create_code("user-b")
        assert store.consume_code(code_a) == "user-a"
        assert store.consume_code(code_b) == "user-b"


class TestConsumeCode:
    async def test_valid_code_returns_user_id(self):
        store = VerificationStore(ttl_seconds=300)
        code = store.create_code("user-42")
        assert store.consume_code(code) == "user-42"

    async def test_consumed_code_cannot_be_reused(self):
        store = VerificationStore(ttl_seconds=300)
        code = store.create_code("user-1")
        store.consume_code(code)
        assert store.consume_code(code) is None

    async def test_unknown_code_returns_none(self):
        store = VerificationStore(ttl_seconds=300)
        assert store.consume_code("000000") is None

    async def test_expired_code_returns_none(self):
        store = VerificationStore(ttl_seconds=0)  # instant expiry
        code = store.create_code("user-1")
        # Force expiry by manipulating internal state.
        store._pending[code] = (
            store._pending[code][0],
            datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert store.consume_code(code) is None


class TestPendingCount:
    async def test_empty_store(self):
        store = VerificationStore(ttl_seconds=300)
        assert store.pending_count == 0

    async def test_counts_active_codes(self):
        store = VerificationStore(ttl_seconds=300)
        store.create_code("user-1")
        store.create_code("user-2")
        assert store.pending_count == 2

    async def test_does_not_count_expired(self):
        store = VerificationStore(ttl_seconds=0)
        code = store.create_code("user-1")
        store._pending[code] = (
            store._pending[code][0],
            datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        assert store.pending_count == 0

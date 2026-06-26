"""In-memory verification code store for Telegram linking.

Codes are 6-digit strings, one active per user. A new code replaces any
previous one. Codes expire after ``ttl_seconds`` (default 5 minutes).

This store lives in-process and is NOT persisted — if the server restarts,
pending codes are lost. That's acceptable: users simply request a new code.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone


class VerificationStore:
    """Pending Telegram verification codes with TTL."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        # code -> (user_id, expires_at)
        self._pending: dict[str, tuple[str, datetime]] = {}

    def create_code(self, user_id: str) -> str:
        """Generate a 6-digit code for ``user_id``, replacing any previous one."""
        # Evict any existing code for this user.
        self._pending = {
            code: (uid, exp)
            for code, (uid, exp) in self._pending.items()
            if uid != user_id
        }
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires = datetime.now(timezone.utc) + timedelta(seconds=self._ttl)
        self._pending[code] = (user_id, expires)
        return code

    def consume_code(self, code: str) -> str | None:
        """Validate and consume a code. Returns the user_id or None.

        The code is removed after consumption (one-time use). Expired codes
        are silently discarded.
        """
        entry = self._pending.pop(code, None)
        if entry is None:
            return None
        user_id, expires = entry
        if datetime.now(timezone.utc) > expires:
            return None
        return user_id

    @property
    def pending_count(self) -> int:
        """Number of non-expired pending codes."""
        now = datetime.now(timezone.utc)
        return sum(1 for _, exp in self._pending.values() if exp > now)

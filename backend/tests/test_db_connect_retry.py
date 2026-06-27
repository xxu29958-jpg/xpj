"""ADR-0047 §3: startup DB connect-retry gate (``wait_for_db``).

Under the Windows-service model the SCM can report the PostgreSQL service
RUNNING before it actually accepts connections, so the backend must wait
(bounded) for the DB instead of crashing on the first connect — the
"die after 4 seconds" failure. These tests drive ``wait_for_db`` with an
injected fake engine so they exercise the retry/backoff/timeout logic without
needing a real not-yet-ready PostgreSQL.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.exc import OperationalError

from app.database import wait_for_db


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        return None


class _FakeEngine:
    """``connect()`` raises ``OperationalError`` ``fails`` times, then succeeds."""

    def __init__(self, fails: int) -> None:
        self.fails = fails
        self.calls = 0

    def connect(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        return _FakeConn()


def test_wait_for_db_retries_until_ready():
    eng = _FakeEngine(fails=2)
    wait_for_db(db_engine=eng, timeout_seconds=5, initial_interval=0.01, max_interval=0.02)
    assert eng.calls == 3  # two failures, then the connection succeeds


def test_wait_for_db_healthy_is_a_single_instant_attempt():
    """Dev/test path: the DB is already up, so the gate is a no-op (no sleep)."""
    eng = _FakeEngine(fails=0)
    started = time.monotonic()
    wait_for_db(db_engine=eng, timeout_seconds=5)
    assert eng.calls == 1
    assert time.monotonic() - started < 0.5


def test_wait_for_db_times_out_with_clear_error():
    eng = _FakeEngine(fails=10**9)
    with pytest.raises(TimeoutError, match="did not accept connections") as excinfo:
        wait_for_db(db_engine=eng, timeout_seconds=0.05, initial_interval=0.01, max_interval=0.02)
    # The opaque per-attempt OperationalError is chained, not swallowed.
    assert isinstance(excinfo.value.__cause__, OperationalError)

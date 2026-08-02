"""Focused runtime checks used by the C07 money migration tests."""

from __future__ import annotations

from sqlalchemy import text

from app.database import engine
from app.database._c07_production_connection import _apply_server_deadline
from app.database._c07_transaction_timeout import c07_prearmed_transaction


def assert_production_deadline_preserves_tighter_timeouts() -> None:
    with (
        engine.connect() as connection,
        c07_prearmed_transaction(connection, timeout_ms=900),
    ):
        for name, value in (
            ("statement_timeout", "425ms"),
            ("lock_timeout", "175ms"),
        ):
            connection.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": name, "value": value},
            )

        effective = _apply_server_deadline(
            connection,
            timeout_ms=60_000,
        )
        observed = connection.execute(
            text(
                "SELECT current_setting('transaction_timeout'), "
                "current_setting('statement_timeout'), "
                "current_setting('lock_timeout')"
            )
        ).one()

    assert effective == {
        "transaction_timeout": 900,
        "statement_timeout": 425,
        "lock_timeout": 175,
    }
    assert tuple(observed) == ("900ms", "425ms", "175ms")

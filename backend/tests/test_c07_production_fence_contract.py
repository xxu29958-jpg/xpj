"""Unit contracts for the C07 production-only live writer fence."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.database import _c07_production_fence as shape
from app.database._c07_production_contract import C07ProductionMigrationError


class _FenceConnection:
    def __init__(self, **overrides: int | bool) -> None:
        self.values: dict[str, int | bool] = {
            "other_clients": 0,
            "public_connect": False,
            "unfenced_login": 0,
            "external_elevated": 0,
            "prepared_capability": 0,
            "prepared_transactions": 0,
            "logical_subscriptions": 0,
            "unexpected_workers": 0,
        }
        self.values.update(overrides)
        self.cleared_snapshot = False

    def execute(self, statement, *args, **kwargs):
        assert "pg_stat_clear_snapshot" in str(statement)
        self.cleared_snapshot = True
        return SimpleNamespace()

    def scalar(self, statement, params=None):
        sql = str(statement)
        if "backend_type = 'client backend'" in sql:
            return self.values["other_clients"]
        if "aclexplode" in sql:
            return self.values["public_connect"]
        if "rolcanlogin" in sql:
            assert params == {"migrator": "ticketbox_migrator"}
            return self.values["unfenced_login"]
        if "rolsuper OR rolcreatedb" in sql:
            return self.values["external_elevated"]
        if "max_prepared_transactions" in sql:
            return self.values["prepared_capability"]
        if "pg_prepared_xacts" in sql:
            return self.values["prepared_transactions"]
        if "pg_subscription" in sql:
            return self.values["logical_subscriptions"]
        if "backend_type NOT IN" in sql:
            return self.values["unexpected_workers"]
        raise AssertionError(f"unexpected C07 fence query: {sql}")


def test_production_writer_fence_accepts_only_a_fully_quiet_database() -> None:
    connection = _FenceConnection()

    shape._assert_production_writer_fence(connection)

    assert connection.cleared_snapshot is True


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"other_clients": 1}, "another client backend"),
        ({"public_connect": True}, "PUBLIC CONNECT"),
        ({"unfenced_login": 1}, "unfenced login role"),
        ({"external_elevated": 1}, "external elevated authority"),
        ({"prepared_capability": 1}, "prepared/logical/background writer"),
        ({"prepared_transactions": 1}, "prepared/logical/background writer"),
        ({"logical_subscriptions": 1}, "prepared/logical/background writer"),
        ({"unexpected_workers": 1}, "prepared/logical/background writer"),
    ),
)
def test_production_writer_fence_fails_closed(
    override: dict[str, int | bool],
    message: str,
) -> None:
    with pytest.raises(C07ProductionMigrationError, match=message):
        shape._assert_production_writer_fence(_FenceConnection(**override))

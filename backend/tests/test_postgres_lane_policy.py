from __future__ import annotations

import pytest

from tests._infra.lane_policy import postgres_test_markers


@pytest.mark.parametrize(
    ("nodeid", "expected"),
    [
        ("tests/test_reports.py::test_monthly_totals", ()),
        (
            "tests/test_expense_optimistic_concurrency.py::test_two_sessions_update",
            ("real_db",),
        ),
        (
            "tests/test_alembic_tag_migration.py::test_round_trip",
            ("real_db", "stateful_serial"),
        ),
        (
            "tests/test_auth_bootstrap.py::test_bootstrap_owner_accepts_valid_secret",
            ("real_db", "stateful_serial"),
        ),
        (
            "tests\\test_db_migration_owner_preflight.py::test_owner_preflight",
            ("real_db", "stateful_serial", "cluster_serial"),
        ),
        (
            "tests/test_reports.py::test_export[tests/test_alembic_fake.py::case]",
            (),
        ),
    ],
)
def test_postgres_lane_policy_is_explicit(
    nodeid: str,
    expected: tuple[str, ...],
) -> None:
    assert postgres_test_markers(nodeid) == expected

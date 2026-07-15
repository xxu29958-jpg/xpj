from __future__ import annotations

import pytest

from tests._infra.lane_policy import (
    legacy_real_db_marker_required,
    postgres_marker_contract_violation,
)


@pytest.mark.parametrize(
    ("nodeid", "expected_real_db"),
    [
        ("tests/test_reports.py::test_monthly_totals", False),
        (
            "tests/test_expense_optimistic_concurrency.py::test_two_sessions_update",
            True,
        ),
        (
            "tests/test_alembic_tag_migration.py::test_round_trip",
            False,
        ),
        (
            "tests/test_auth_bootstrap.py::test_bootstrap_owner_accepts_valid_secret",
            False,
        ),
        (
            "tests\\test_db_migration_owner_preflight.py::test_owner_preflight",
            False,
        ),
        (
            "tests/test_reports.py::test_export[tests/test_alembic_fake.py::case]",
            False,
        ),
    ],
)
def test_nodeid_policy_only_retains_legacy_real_db_exceptions(
    nodeid: str,
    expected_real_db: bool,
) -> None:
    assert legacy_real_db_marker_required(nodeid) is expected_real_db
    assert (
        postgres_marker_contract_violation(
            nodeid,
            {"real_db", "stateful_serial", "cluster_serial"},
        )
        is None
    )
    assert "requires real_db" in (
        postgres_marker_contract_violation(nodeid, {"stateful_serial"}) or ""
    )
    assert "requires stateful_serial" in (
        postgres_marker_contract_violation(
            nodeid,
            {"real_db", "cluster_serial"},
        )
        or ""
    )

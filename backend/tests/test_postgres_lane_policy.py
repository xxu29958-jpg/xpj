from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._infra.lane_policy import (
    postgres_marker_contract_violation,
    xdist_worker_identity_violation,
)
from tests._infra.postgres_resource_contract import (
    postgres_source_marker_contract_violation,
    required_postgres_marker_for_callables,
    required_postgres_marker_for_source,
)
from tests._infra.postgres_resource_examples import (
    ImportedClusterHelper,
    imported_cluster_fixture,
    imported_cluster_helper,
)

pytestmark = pytest.mark.parallel_safe


def test_postgres_resource_markers_require_explicit_nesting() -> None:
    nodeid = "tests/test_example.py::test_resource_contract"
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


def test_postgres_resource_classification_uses_executable_source() -> None:
    assert (
        required_postgres_marker_for_source(
            """
def test_role_change(connection):
    connection.execute(text("DROP ROLE IF EXISTS xpj_test_role"))
""",
            root_names=("test_role_change",),
        )
        == "cluster_serial"
    )
    assert (
        required_postgres_marker_for_source(
            """
def test_local_sql(connection):
    statement = "DROP ROLE IF EXISTS xpj_resource_contract"
    connection.execute(statement)
""",
            root_names=("test_local_sql",),
        )
        == "cluster_serial"
    )
    assert (
        required_postgres_marker_for_source(
            """
from alembic import command

def _migrate():
    command.upgrade(config, "head")

def test_upgrade():
    _migrate()
""",
            root_names=("test_upgrade",),
        )
        == "stateful_serial"
    )
    assert (
        required_postgres_marker_for_source(
            """
def test_diagnostic(events):
    assert not any("DROP DATABASE" in event for event in events)
""",
            root_names=("test_diagnostic",),
        )
        is None
    )
    assert (
        required_postgres_marker_for_source(
            """
DROP_SQL = "DROP DATABASE IF EXISTS xpj_resource_contract"

class Helper:
    @staticmethod
    def drop(connection):
        connection.execute(DROP_SQL)

class TestResource:
    def test_drop(self, connection):
        Helper.drop(connection)
""",
            root_names=("test_drop",),
        )
        == "cluster_serial"
    )


def _call_imported_helper(connection: object) -> None:
    imported_cluster_helper(connection)


def _call_imported_class_method(connection: object) -> None:
    ImportedClusterHelper.drop_role(connection)


def _benign_test_root() -> None:
    return None


def test_postgres_resource_classification_follows_project_callables_and_fixtures() -> None:
    assert (
        required_postgres_marker_for_callables((_call_imported_helper,))
        == "cluster_serial"
    )
    assert (
        required_postgres_marker_for_callables((_call_imported_class_method,))
        == "cluster_serial"
    )
    assert (
        required_postgres_marker_for_callables((imported_cluster_fixture,))
        == "cluster_serial"
    )
    fake_item = SimpleNamespace(
        obj=_benign_test_root,
        name="test_benign",
        nodeid="tests/test_fake.py::test_benign",
        path=Path(__file__).resolve(),
        _fixtureinfo=SimpleNamespace(
            name2fixturedefs={
                "shared_fixture": (SimpleNamespace(func=imported_cluster_helper),)
            }
        ),
    )
    violation = postgres_source_marker_contract_violation(fake_item, set())
    assert violation is not None
    assert "cluster_serial" in violation


@pytest.mark.parametrize(
    ("ambient", "runtime", "expected"),
    [
        (None, None, None),
        ("gw0", "gw0", None),
        ("gw0", None, "clear inherited"),
        (None, "gw0", "missing PYTEST_XDIST_WORKER"),
        ("gw0", "gw1", "does not match"),
    ],
)
def test_xdist_worker_identity_must_have_one_runtime_authority(
    ambient: str | None,
    runtime: str | None,
    expected: str | None,
) -> None:
    violation = xdist_worker_identity_violation(
        ambient_worker=ambient,
        runtime_worker=runtime,
    )

    if expected is None:
        assert violation is None
    else:
        assert expected in (violation or "")

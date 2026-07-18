from __future__ import annotations

from pathlib import Path

import pytest

from scripts.test_impact_selection import (
    GitChange,
    select_impacted_tests,
)

pytestmark = pytest.mark.parallel_safe


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _backend_fixture(tmp_path: Path) -> Path:
    backend = tmp_path / "backend"
    _write(
        backend,
        "app/services/amounts.py",
        "def calculate():\n    return 1\n",
    )
    _write(
        backend,
        "app/routes/expenses.py",
        "from fastapi import APIRouter\n"
        "from app.services.amounts import calculate\n"
        "router = APIRouter(prefix='/api/expenses')\n"
        "@router.post('/{expense_id}')\n"
        "def update_expense(expense_id: str):\n"
        "    return calculate()\n",
    )
    _write(
        backend,
        "tests/test_amounts.py",
        "from app.services.amounts import calculate\n"
        "def test_amount():\n"
        "    assert calculate() == 1\n",
    )
    _write(
        backend,
        "tests/test_expense_route.py",
        "def test_route(client, expense_id):\n"
        "    assert client.post(f'/api/expenses/{expense_id}').status_code == 200\n",
    )
    for index in range(3):
        _write(
            backend,
            f"tests/test_unrelated_{index}.py",
            f"def test_unrelated_{index}():\n    assert True\n",
        )
    return backend


def test_service_change_selects_direct_and_route_consumers(tmp_path: Path) -> None:
    backend = _backend_fixture(tmp_path)

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/amounts.py")],
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == (
        "tests/test_amounts.py",
        "tests/test_expense_route.py",
    )


def test_changed_test_file_selects_itself(tmp_path: Path) -> None:
    backend = _backend_fixture(tmp_path)

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/tests/test_unrelated_0.py")],
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == ("tests/test_unrelated_0.py",)


@pytest.mark.parametrize(
    "change",
    [
        GitChange("M", "backend/app/config.py"),
        GitChange("M", "backend/app/database/_seed.py"),
        GitChange("M", "backend/app/models/expense.py"),
        GitChange("M", "backend/app/services/expense_service/__init__.py"),
        GitChange("M", "backend/alembic/versions/0001.py"),
        GitChange("M", "backend/requirements.txt"),
        GitChange("M", "backend/scripts/codebase_audit_gate.py"),
        GitChange("D", "backend/app/services/amounts.py"),
        GitChange("R", "docs/amounts.py", old_path="backend/app/services/amounts.py"),
    ],
)
def test_shared_or_destructive_changes_fall_back_to_full(
    tmp_path: Path,
    change: GitChange,
) -> None:
    backend = _backend_fixture(tmp_path)

    selection = select_impacted_tests(backend, [change])

    assert selection.mode == "full"
    assert selection.selected_tests == ()


def test_unreferenced_production_change_falls_back_to_full(tmp_path: Path) -> None:
    backend = _backend_fixture(tmp_path)
    _write(backend, "app/services/new_unreferenced.py", "VALUE = 1\n")

    selection = select_impacted_tests(
        backend,
        [GitChange("A", "backend/app/services/new_unreferenced.py")],
    )

    assert selection.mode == "full"
    assert selection.reasons[0].startswith("no-test-dependency-proof:")


def test_selection_covering_most_test_files_falls_back_to_full(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/shared.py", "VALUE = 1\n")
    for index in range(10):
        _write(
            backend,
            f"tests/test_shared_{index}.py",
            "from app.services.shared import VALUE\n"
            f"def test_shared_{index}():\n"
            "    assert VALUE == 1\n",
        )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/shared.py")],
    )

    assert selection.mode == "full"
    assert selection.reasons == ("selection-too-broad:10/10",)


def test_cross_repo_contract_change_falls_back_to_full(tmp_path: Path) -> None:
    backend = _backend_fixture(tmp_path)

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "android/app/src/main/java/example.kt")],
    )

    assert selection.mode == "full"


def test_unknown_repository_root_falls_back_to_full(tmp_path: Path) -> None:
    backend = _backend_fixture(tmp_path)

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "future-surface/runtime.contract")],
    )

    assert selection.mode == "full"
    assert selection.reasons == (
        "unclassified-repository-change:future-surface/runtime.contract",
    )


@pytest.mark.parametrize(
    "path",
    [
        "backend/packaging/launch.py",
        "android/app/src/main/res/values/strings.xml",
        "desktop/backend_manager/manager.py",
        "scripts/check_cloudflare_endpoint.ps1",
    ],
)
def test_unmodeled_cross_repo_consumers_fall_back_to_full(
    tmp_path: Path,
    path: str,
) -> None:
    backend = _backend_fixture(tmp_path)

    selection = select_impacted_tests(
        backend,
        [GitChange("M", path)],
    )

    assert selection.mode == "full"


def test_dynamic_route_contract_falls_back_to_full(tmp_path: Path) -> None:
    backend = _backend_fixture(tmp_path)
    _write(
        backend,
        "app/routes/expenses.py",
        "from fastapi import APIRouter\n"
        "from app.services.amounts import calculate\n"
        "PREFIX = '/api/expenses'\n"
        "router = APIRouter(prefix=PREFIX)\n"
        "@router.post('/{expense_id}')\n"
        "def update_expense(expense_id: str):\n"
        "    return calculate()\n",
    )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/amounts.py")],
    )

    assert selection.mode == "full"
    assert selection.reasons[0].startswith("route-impact-unproven:")


def test_dynamic_direct_route_registration_falls_back_to_full(
    tmp_path: Path,
) -> None:
    backend = _backend_fixture(tmp_path)
    _write(
        backend,
        "app/routes/expenses.py",
        "from fastapi import APIRouter\n"
        "from app.services.amounts import calculate\n"
        "router = APIRouter(prefix='/api/expenses')\n"
        "PATH = '/{expense_id}'\n"
        "def update_expense(expense_id: str):\n"
        "    return calculate()\n"
        "router.add_api_route(PATH, update_expense, methods=['POST'])\n",
    )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/amounts.py")],
    )

    assert selection.mode == "full"
    assert selection.reasons[0].startswith("route-impact-unproven:")


def test_static_direct_route_registration_selects_literal_consumers(
    tmp_path: Path,
) -> None:
    backend = _backend_fixture(tmp_path)
    _write(
        backend,
        "app/routes/expenses.py",
        "from fastapi import APIRouter\n"
        "from app.services.amounts import calculate\n"
        "router = APIRouter(prefix='/api/expenses')\n"
        "def update_expense(expense_id: str):\n"
        "    return calculate()\n"
        "router.add_api_route('/{expense_id}', update_expense, methods=['POST'])\n",
    )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/amounts.py")],
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == (
        "tests/test_amounts.py",
        "tests/test_expense_route.py",
    )


def test_route_change_keeps_base_and_head_path_consumers(tmp_path: Path) -> None:
    backend = _backend_fixture(tmp_path)
    _write(
        backend,
        "app/routes/expenses.py",
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/api/expenses-v2')\n"
        "@router.post('/{expense_id}')\n"
        "def update_expense(expense_id: str):\n"
        "    return expense_id\n",
    )
    _write(
        backend,
        "tests/test_expense_route_v2.py",
        "def test_route_v2(client, expense_id):\n"
        "    assert client.post(f'/api/expenses-v2/{expense_id}').status_code == 200\n",
    )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/routes/expenses.py")],
        historical_route_patterns=("/api/expenses/{expense_id}",),
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == (
        "tests/test_expense_route.py",
        "tests/test_expense_route_v2.py",
    )


def test_route_path_in_helper_selects_each_test_importing_that_helper(
    tmp_path: Path,
) -> None:
    backend = _backend_fixture(tmp_path)
    _write(
        backend,
        "tests/_infra/expense_route_helper.py",
        "def expense_path(expense_id: str) -> str:\n"
        "    return f'/api/expenses/{expense_id}'\n",
    )
    _write(
        backend,
        "tests/test_expense_route_helper_consumer.py",
        "from tests._infra.expense_route_helper import expense_path\n"
        "def test_helper_route(client):\n"
        "    assert client.post(expense_path('one')).status_code == 200\n",
    )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/routes/expenses.py")],
    )

    assert selection.mode == "selected"
    assert "tests/test_expense_route_helper_consumer.py" in selection.selected_tests


def test_affected_pytest_fixture_boundary_falls_back_to_full(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/identity.py", "VALUE = 1\n")
    _write(
        backend,
        "tests/conftest.py",
        "import pytest\n"
        "from app.services.identity import VALUE\n"
        "@pytest.fixture\n"
        "def identity_value():\n"
        "    return VALUE\n",
    )
    _write(
        backend,
        "tests/test_identity.py",
        "def test_identity(identity_value):\n"
        "    assert identity_value == 1\n",
    )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/identity.py")],
    )

    assert selection.mode == "full"
    assert selection.reasons == (
        "pytest-fixture-closure-unproven:tests.conftest",
    )


def test_import_propagation_does_not_stop_at_database_module(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/identity.py", "VALUE = 1\n")
    _write(
        backend,
        "app/database.py",
        "from app.services.identity import VALUE\n",
    )
    _write(
        backend,
        "tests/test_database_consumer.py",
        "from app.database import VALUE\n"
        "def test_value():\n"
        "    assert VALUE == 1\n",
    )
    for index in range(3):
        _write(
            backend,
            f"tests/test_other_{index}.py",
            f"def test_other_{index}():\n    pass\n",
        )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/identity.py")],
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == ("tests/test_database_consumer.py",)


def test_direct_composition_root_dependency_keeps_main_consumers(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/health.py", "def health():\n    return 'ok'\n")
    _write(
        backend,
        "app/main.py",
        "from app.services.health import health\n"
        "APP_HEALTH = health\n",
    )
    _write(
        backend,
        "tests/test_health_unit.py",
        "from app.services.health import health\n"
        "def test_health():\n"
        "    assert health() == 'ok'\n",
    )
    _write(
        backend,
        "tests/test_main_health.py",
        "from app.main import APP_HEALTH\n"
        "def test_main_health():\n"
        "    assert APP_HEALTH() == 'ok'\n",
    )
    for index in range(3):
        _write(backend, f"tests/test_other_{index}.py", f"def test_other_{index}():\n    pass\n")

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/health.py")],
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == (
        "tests/test_health_unit.py",
        "tests/test_main_health.py",
    )

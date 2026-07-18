from __future__ import annotations

from pathlib import Path

import pytest

from scripts.test_impact_selection import (
    GitChange,
    _parse_name_status,
    route_paths,
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


def test_package_initializer_execution_propagates_to_each_facade_consumer(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/facade/first.py", "def alpha():\n    return 1\n")
    _write(backend, "app/services/facade/second.py", "def beta():\n    return 2\n")
    _write(
        backend,
        "app/services/facade/__init__.py",
        "from app.services.facade.first import alpha\n"
        "from app.services.facade.second import beta\n",
    )
    _write(
        backend,
        "app/routes/alpha.py",
        "from fastapi import APIRouter\n"
        "from app.services.facade import alpha\n"
        "router = APIRouter(prefix='/api/alpha')\n"
        "@router.get('')\n"
        "def get_alpha():\n"
        "    return alpha()\n",
    )
    _write(
        backend,
        "app/routes/beta.py",
        "from fastapi import APIRouter\n"
        "from app.services.facade import beta\n"
        "router = APIRouter(prefix='/api/beta')\n"
        "@router.get('')\n"
        "def get_beta():\n"
        "    return beta()\n",
    )
    _write(
        backend,
        "app/routes/facade_module.py",
        "from fastapi import APIRouter\n"
        "from app.services import facade\n"
        "router = APIRouter(prefix='/api/facade-module')\n"
        "@router.get('')\n"
        "def get_alpha_from_module():\n"
        "    return facade.alpha()\n",
    )
    _write(backend, "tests/test_alpha.py", "def test_alpha(client):\n    client.get('/api/alpha')\n")
    _write(backend, "tests/test_beta.py", "def test_beta(client):\n    client.get('/api/beta')\n")
    _write(
        backend,
        "tests/test_facade_module.py",
        "def test_facade_module(client):\n    client.get('/api/facade-module')\n",
    )
    for index in range(3):
        _write(backend, f"tests/test_other_{index}.py", f"def test_other_{index}():\n    pass\n")

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/facade/first.py")],
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == (
        "tests/test_alpha.py",
        "tests/test_beta.py",
        "tests/test_facade_module.py",
    )


def test_source_scanner_declares_its_path_dependency(tmp_path: Path) -> None:
    backend = _backend_fixture(tmp_path)
    _write(
        backend,
        "tests/test_route_scanner.py",
        "from pathlib import Path\n"
        "TEST_IMPACT_SOURCE_PREFIXES = ('backend/app/routes/',)\n"
        "def test_routes():\n"
        "    assert list((Path('app') / 'routes').glob('*.py'))\n",
    )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/routes/expenses.py")],
    )

    assert selection.mode == "selected"
    assert "tests/test_route_scanner.py" in selection.selected_tests


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


def test_route_parser_combines_each_router_prefix(tmp_path: Path) -> None:
    route = _write(
        tmp_path,
        "routes.py",
        "from fastapi import APIRouter\n"
        "first = APIRouter(prefix='/api/one')\n"
        "second = APIRouter(prefix='/api/two')\n"
        "@first.get('/{item_id}')\n"
        "def one():\n"
        "    pass\n"
        "@second.delete('')\n"
        "def two():\n"
        "    pass\n",
    )

    assert route_paths(route) == ("/api/one/{item_id}", "/api/two")


def test_git_name_status_parser_keeps_destructive_identity() -> None:
    changes = _parse_name_status(
        b"M\0backend/app/a.py\0R100\0backend/app/old.py\0docs/new.py\0"
    )

    assert changes == (
        GitChange("M", "backend/app/a.py"),
        GitChange("R", "docs/new.py", old_path="backend/app/old.py"),
    )

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.test_impact_git_evidence import parse_name_status
from scripts.test_impact_selection import (
    GitChange,
    select_impacted_tests,
)
from scripts.test_impact_source_graph import route_paths

pytestmark = pytest.mark.parallel_safe


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _route_backend_fixture(tmp_path: Path) -> Path:
    backend = tmp_path / "backend"
    _write(
        backend,
        "app/routes/expenses.py",
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/api/expenses')\n"
        "@router.post('/{expense_id}')\n"
        "def update_expense(expense_id: str):\n"
        "    return expense_id\n",
    )
    _write(
        backend,
        "tests/test_expense_route.py",
        "def test_route(client):\n"
        "    assert client.post('/api/expenses/one').status_code == 200\n",
    )
    for index in range(3):
        _write(
            backend,
            f"tests/test_unrelated_{index}.py",
            f"def test_unrelated_{index}():\n    assert True\n",
        )
    return backend


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
    for name in ("alpha", "beta"):
        _write(
            backend,
            f"app/routes/{name}.py",
            "from fastapi import APIRouter\n"
            f"from app.services.facade import {name}\n"
            f"router = APIRouter(prefix='/api/{name}')\n"
            "@router.get('')\n"
            f"def get_value():\n    return {name}()\n",
        )
        _write(
            backend,
            f"tests/test_{name}.py",
            f"def test_{name}(client):\n    client.get('/api/{name}')\n",
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
    _write(
        backend,
        "tests/test_facade_module.py",
        "def test_facade_module(client):\n"
        "    client.get('/api/facade-module')\n",
    )
    for index in range(3):
        _write(
            backend,
            f"tests/test_other_{index}.py",
            f"def test_other_{index}():\n    pass\n",
        )

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
    backend = _route_backend_fixture(tmp_path)
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


def test_non_test_source_scanner_declaration_reaches_its_test(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/isolated.py", "VALUE = 1\n")
    _write(
        backend,
        "scripts/service_scanner.py",
        "TEST_IMPACT_SOURCE_PREFIXES = ('backend/app/services/',)\n"
        "def scan():\n"
        "    return True\n",
    )
    _write(
        backend,
        "tests/test_service_scanner.py",
        "from scripts.service_scanner import scan\n"
        "def test_scan():\n"
        "    assert scan()\n",
    )
    for index in range(3):
        _write(
            backend,
            f"tests/test_other_{index}.py",
            f"def test_other_{index}():\n    pass\n",
        )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/isolated.py")],
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == ("tests/test_service_scanner.py",)


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


def test_route_parser_combines_decorated_and_direct_registration(
    tmp_path: Path,
) -> None:
    route = _write(
        tmp_path,
        "routes.py",
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/api')\n"
        "@router.api_route('/items', methods=['GET'])\n"
        "def items():\n"
        "    pass\n"
        "def stream():\n"
        "    pass\n"
        "router.add_websocket_route('/stream', stream)\n",
    )

    assert route_paths(route) == ("/api/items", "/api/stream")


def test_git_name_status_parser_keeps_destructive_identity() -> None:
    changes = parse_name_status(
        b"M\0backend/app/a.py\0R100\0backend/app/old.py\0docs/new.py\0"
    )

    assert changes == (
        GitChange("M", "backend/app/a.py"),
        GitChange("R", "docs/new.py", old_path="backend/app/old.py"),
    )

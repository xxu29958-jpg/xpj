from __future__ import annotations

from pathlib import Path

import pytest

from scripts.test_impact_selection import GitChange, select_impacted_tests

pytestmark = pytest.mark.parallel_safe


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _assert_full_for_change(backend: Path, changed_path: str) -> None:
    selection = select_impacted_tests(
        backend,
        [GitChange("M", changed_path)],
    )
    assert selection.mode == "full"
    assert selection.reasons[0].startswith("python-import-impact-unproven:")


@pytest.mark.parametrize(
    "loader_import,loader_call",
    (
        ("import runpy", "runpy.run_path"),
        ("from runpy import run_path", "run_path"),
    ),
)
def test_nonliteral_file_loader_falls_back_to_full(
    tmp_path: Path,
    loader_import: str,
    loader_call: str,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/shared.py", "VALUE = 1\n")
    _write(
        backend,
        "tests/test_shared_loader.py",
        "from pathlib import Path\n"
        f"{loader_import}\n"
        "TEST_IMPACT_SOURCE_PREFIXES = ('backend/app/',)\n"
        "def test_shared():\n"
        f"    assert {loader_call}(Path('app') / 'shared.py')['VALUE'] == 1\n",
    )

    _assert_full_for_change(backend, "backend/app/shared.py")


def test_dynamic_pytest_plugin_declaration_falls_back_to_full(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/isolated.py", "VALUE = 1\n")
    _write(
        backend,
        "tests/plugin_support.py",
        "import pytest\n"
        "@pytest.fixture\n"
        "def isolated_value():\n"
        "    from app.services.isolated import VALUE\n"
        "    return VALUE\n",
    )
    _write(
        backend,
        "tests/conftest.py",
        "def plugin_name():\n"
        "    return 'tests.plugin_support'\n"
        "pytest_plugins = [plugin_name()]\n",
    )
    _write(
        backend,
        "tests/test_isolated.py",
        "def test_isolated(isolated_value):\n"
        "    assert isolated_value == 1\n",
    )

    _assert_full_for_change(backend, "backend/app/services/isolated.py")


def test_declared_scope_cannot_hide_an_unresolved_dynamic_import(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/providers/alpha.py", "VALUE = 1\n")
    _write(
        backend,
        "tests/test_dynamic_provider.py",
        "import importlib\n"
        "TEST_IMPACT_SOURCE_PREFIXES = ('backend/app/services/',)\n"
        "PROVIDER = 'alpha'\n"
        "def test_provider():\n"
        "    module = importlib.import_module(f'app.providers.{PROVIDER}')\n"
        "    assert module.VALUE == 1\n",
    )

    _assert_full_for_change(backend, "backend/app/providers/alpha.py")

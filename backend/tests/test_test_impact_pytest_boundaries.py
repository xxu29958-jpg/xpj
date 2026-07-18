from __future__ import annotations

from pathlib import Path

import pytest

from scripts.test_impact_selection import GitChange, select_impacted_tests

pytestmark = pytest.mark.parallel_safe


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_declared_scanner_reaching_conftest_falls_back_to_full(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/identity.py", "VALUE = 1\n")
    _write(
        backend,
        "tests/source_fixture.py",
        "TEST_IMPACT_SOURCE_PREFIXES = ('backend/app/services/',)\n"
        "def source_value():\n"
        "    return 1\n",
    )
    _write(
        backend,
        "tests/conftest.py",
        "import pytest\n"
        "from tests.source_fixture import source_value\n"
        "@pytest.fixture\n"
        "def identity_value():\n"
        "    return source_value()\n",
    )
    _write(
        backend,
        "tests/test_identity.py",
        "from app.services.identity import VALUE\n"
        "def test_identity(identity_value):\n"
        "    assert VALUE == identity_value\n",
    )

    selection = select_impacted_tests(
        backend,
        [GitChange("M", "backend/app/services/identity.py")],
    )

    assert selection.mode == "full"
    assert selection.reasons == (
        "pytest-fixture-closure-unproven:tests.conftest",
    )


def test_pytest_suffix_named_tests_participate_in_selection(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    _write(backend, "app/services/provider.py", "VALUE = 1\n")
    _write(
        backend,
        "tests/test_provider.py",
        "from app.services.provider import VALUE\n"
        "def test_provider():\n"
        "    assert VALUE == 1\n",
    )
    _write(
        backend,
        "tests/provider_test.py",
        "from app.services.provider import VALUE\n"
        "def test_provider_suffix():\n"
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
        [GitChange("M", "backend/app/services/provider.py")],
    )

    assert selection.mode == "selected"
    assert selection.selected_tests == (
        "tests/provider_test.py",
        "tests/test_provider.py",
    )

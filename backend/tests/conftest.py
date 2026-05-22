"""Top-level pytest hooks and fixtures.

Implementation lives in ``tests/_infra/``:

- ``env``      — TEST_* path/token constants + ``os.environ`` wiring
- ``assets``   — static byte resources (PNG_BYTES, ...)
- ``identity`` — TestIdentity dataclass + seed_identity factory
- ``db``       — schema / data lifecycle (reset, cleanup)
- ``client``   — TestClient + dependency overrides

Tests import constants and the ``TestIdentity`` type directly from those
modules. This file only defines the fixtures and the session-end hook.
"""

from __future__ import annotations

import pytest

# Importing tests._infra.env sets os.environ before any app.* import.
from tests._infra import env  # noqa: F401
from tests._infra.client import make_test_client
from tests._infra.db import cleanup_runtime, reset_db_state
from tests._infra.identity import TestIdentity, seed_identity


@pytest.fixture()
def identity() -> TestIdentity:
    reset_db_state()
    return seed_identity()


@pytest.fixture()
def client(identity: TestIdentity):
    with make_test_client() as test_client:
        yield test_client


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "file_backed_only: test only meaningful against a file-backed SQLite; "
        "skipped under the default in-memory lane. Run via XPJ_TEST_FILE_BACKED=1.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    from app.database import settings as _settings

    url = _settings.database_url
    if ":memory:" not in url and url != "sqlite://":
        return
    skip_marker = pytest.mark.skip(
        reason="file_backed_only: requires file-backed SQLite (set XPJ_TEST_FILE_BACKED=1)."
    )
    for item in items:
        if "file_backed_only" in item.keywords:
            item.add_marker(skip_marker)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    cleanup_runtime()

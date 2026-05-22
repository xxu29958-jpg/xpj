"""TestClient lifecycle: dependency overrides + close.

Bypasses the admin network boundary for the default TestClient (peer=testclient,
host=testserver). The boundary itself is exercised directly in
``tests/test_owner_console.py`` via the network_boundary helper.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient


@contextmanager
def make_test_client() -> Iterator[TestClient]:
    from app.main import app
    from app.network_boundary import require_admin_network_boundary

    app.dependency_overrides[require_admin_network_boundary] = lambda: None
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()

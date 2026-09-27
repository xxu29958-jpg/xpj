"""The duplicate Owner tag-cleanup surface is retired in favor of /web/tags."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local


@pytest.mark.parametrize("local", [False, True])
def test_owner_tag_cleanup_routes_are_retired(client: TestClient, local: bool) -> None:
    if local:
        app.dependency_overrides[_require_local] = lambda: None
    try:
        assert client.get("/owner/tag-cleanup").status_code == 404
        assert client.post(
            "/owner/tag-cleanup/delete",
            data={"public_id": "x", "expected_row_version": "1"},
        ).status_code == 404
    finally:
        app.dependency_overrides.pop(_require_local, None)

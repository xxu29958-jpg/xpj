from __future__ import annotations

from fastapi.testclient import TestClient

from app.database._dataset_restore_security import RESTORE_TABLE_SECURITY
from app.database_model_registry import Base
from migrations.versions._baseline.schema_01 import STATEMENTS as BASELINE_STATEMENTS


def test_cross_surface_ui_preferences_owner_is_physically_retired(
    client: TestClient,
) -> None:
    assert "/api/me/ui-preferences" not in client.app.openapi()["paths"]

    for method in ("GET", "PUT"):
        response = client.request(
            method,
            "/api/me/ui-preferences",
            json={"theme": "midnight"} if method == "PUT" else None,
        )
        assert response.status_code == 404


def test_cross_surface_ui_preferences_storage_is_physically_retired() -> None:
    assert "user_ui_preferences" not in Base.metadata.tables
    assert "user_ui_preferences" not in RESTORE_TABLE_SECURITY
    assert all("user_ui_preferences" not in statement for statement in BASELINE_STATEMENTS)

"""v1.1 Batch 1: CSV import bytes/lines/cell-bytes upper bounds.

These caps live alongside the existing ``MAX_CSV_IMPORT_ROWS=20_000``
limit. Defaults are large enough that real owner imports don't hit
them; lower them via env to exercise the rejection paths.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.config import reset_settings_cache


@pytest.fixture()
def reset_settings(monkeypatch: pytest.MonkeyPatch):
    yield monkeypatch
    reset_settings_cache()


def _post_csv(client: TestClient, *, identity, body: bytes, file_name: str = "x.csv"):
    return client.post(
        "/api/imports/csv",
        headers=identity.app_headers,
        files={"csv_file": (file_name, io.BytesIO(body), "text/csv")},
    )


def test_csv_byte_limit_rejects_oversized_file(
    client: TestClient, *, identity, reset_settings
) -> None:
    reset_settings.setenv("CSV_IMPORT_MAX_BYTES", "64")
    reset_settings_cache()
    body = b"amount_yuan,merchant\n" + b"1.00,Cafe\n" * 200
    response = _post_csv(client, identity=identity, body=body)
    assert response.status_code == 413
    assert response.json()["error"] == "invalid_request"


def test_csv_line_limit_rejects_too_many_data_rows(
    client: TestClient, *, identity, reset_settings
) -> None:
    reset_settings.setenv("CSV_IMPORT_MAX_LINES", "3")
    reset_settings_cache()
    body = b"amount_yuan\n" + b"1.00\n" * 10
    response = _post_csv(client, identity=identity, body=body)
    assert response.status_code == 400


def test_csv_cell_bytes_rejects_oversized_cell(
    client: TestClient, *, identity, reset_settings
) -> None:
    reset_settings.setenv("CSV_IMPORT_MAX_CELL_BYTES", "16")
    reset_settings_cache()
    big_merchant = "M" * 200
    body = f"amount_yuan,merchant\n1.00,{big_merchant}\n".encode()
    response = _post_csv(client, identity=identity, body=body)
    assert response.status_code == 400


def test_csv_within_bounds_succeeds(
    client: TestClient, *, identity, reset_settings
) -> None:
    # Defaults are generous; this just confirms a normal payload still
    # rides through the new code path.
    body = b"amount_yuan,merchant\n1.00,Cafe\n2.00,Diner\n"
    response = _post_csv(client, identity=identity, body=body)
    assert response.status_code == 201, response.text

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from api_contract_helpers import (
    patch_expense,
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import BACKEND_ROOT


def test_upload_pending_image_and_confirm_flow(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == expense_id

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["amount_cents"] is None
    UUID(item["public_id"])
    assert item["category"] == "其他"
    assert item["image_path"].startswith("uploads/")
    assert "\\" not in item["image_path"]
    assert item["image_hash"]

    image_without_token = client.get(f"/api/expenses/{expense_id}/image")
    assert image_without_token.status_code == 401
    assert image_without_token.json()["error"] == "invalid_token"

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 200
    assert image.content == PNG_BYTES

    thumbnail = client.get(
        f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers
    )
    assert thumbnail.status_code == 200
    assert thumbnail.content.startswith(b"\xff\xd8")

    response = client.post(f"/api/expenses/{expense_id}/confirm", headers=identity.app_headers)
    assert response.status_code == 400
    assert response.json()["error"] == "amount_required"

    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 3680,
            "merchant": "美团外卖",
            "category": "餐饮",
            "note": "午饭",
            "expense_time": "2026-05-03T04:20:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["amount_cents"] == 3680

    response = client.post(f"/api/expenses/{expense_id}/confirm", headers=identity.app_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    confirmed = client.get(
        "/api/expenses/confirmed?page=1&page_size=50&month=2026-05&category=餐饮",
        headers=identity.app_headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 1

    categories = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert categories.status_code == 200
    assert "餐饮" in categories.json()["items"]
    assert "吃饭" not in categories.json()["items"]

    months = client.get("/api/expenses/months", headers=identity.app_headers)
    assert months.status_code == 200
    assert "2026-05" in months.json()["items"]

    exported = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮", headers=identity.app_headers
    )
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert "美团外卖" in exported.text
    assert "public_id" in exported.text.splitlines()[0]
    assert "3680" in exported.text

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 3680


def test_thumbnail_is_not_readable_after_original_image_is_deleted(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)

    thumbnail = client.get(
        f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers
    )
    assert thumbnail.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.image_deleted_at = now_utc()
        db.commit()

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 404
    thumbnail = client.get(
        f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers
    )
    assert thumbnail.status_code == 404


def test_confirm_removes_expense_from_pending_and_adds_confirmed(
    client: TestClient, *, identity,
) -> None:
    expense_id = upload_png(client, identity=identity)
    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 1851,
            "merchant": "中国建设银行",
            "category": "餐饮",
            "expense_time": "2026-05-04T08:23:25Z",
        },
    )
    assert response.status_code == 200

    response = client.post(f"/api/expenses/{expense_id}/confirm", headers=identity.app_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    assert all(item["id"] != expense_id for item in pending.json())

    confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=identity.app_headers
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 1
    assert confirmed.json()["items"][0]["id"] == expense_id

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 1851


def test_confirm_delete_after_confirm_hides_image_and_thumbnail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch, *, identity,
) -> None:
    from app.services import cleanup_service

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(
        cleanup_service,
        "get_settings",
        lambda: replace(settings, delete_image_after_confirm=True),
    )

    expense_id = upload_png(client, identity=identity)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.image_path is not None
        assert expense.thumbnail_path is not None
        image_path = BACKEND_ROOT / expense.image_path
        thumbnail_path = BACKEND_ROOT / expense.thumbnail_path
    assert image_path.is_file()
    assert thumbnail_path.is_file()

    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 1851,
            "merchant": "A",
            "category": "餐饮",
            "expense_time": "2026-05-04T08:23:25Z",
        },
    )
    assert response.status_code == 200

    response = client.post(f"/api/expenses/{expense_id}/confirm", headers=identity.app_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "confirmed"
    assert payload["image_deleted_at"] is not None
    assert payload["thumbnail_deleted_at"] is not None
    assert not image_path.exists()
    assert not thumbnail_path.exists()

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 404
    thumbnail = client.get(
        f"/api/expenses/{expense_id}/thumbnail",
        headers=identity.app_headers,
    )
    assert thumbnail.status_code == 404

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.image_deleted_at is not None
        assert expense.thumbnail_deleted_at is not None


def test_deleted_image_does_not_break_confirmed_ledger_data(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)
    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 3680,
            "merchant": "图片已清理商家",
            "category": "餐饮",
            "expense_time": "2026-05-04T08:23:25Z",
        },
    )
    assert response.status_code == 200
    assert (
        client.post(
            f"/api/expenses/{expense_id}/confirm", headers=identity.app_headers
        ).status_code
        == 200
    )

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200
    for path_key in ["image_path", "thumbnail_path"]:
        relative_path = detail.json().get(path_key)
        if relative_path:
            (BACKEND_ROOT / relative_path).unlink(missing_ok=True)

    detail_after_delete = client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert detail_after_delete.status_code == 200
    payload = detail_after_delete.json()
    assert payload["status"] == "confirmed"
    assert payload["amount_cents"] == 3680
    assert payload["merchant"] == "图片已清理商家"

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 404
    assert image.json()["error"] == "image_not_found"

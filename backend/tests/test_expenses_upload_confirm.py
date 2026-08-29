from __future__ import annotations

import re
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from api_contract_helpers import (
    confirm_expense_api,
    patch_expense,
    upload_png,
)
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Expense
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.env import BACKEND_ROOT

_PUBLIC_WEB_ORIGIN = "https://api.example.com"


def _html_form_value(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    assert match is not None, f"missing {name} form field"
    return match.group(1)


def _open_public_web_session(client: TestClient, *, identity) -> tuple[TestClient, dict[str, str]]:
    pairing = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert pairing.status_code == 200, pairing.text

    public = TestClient(
        app,
        base_url=_PUBLIC_WEB_ORIGIN,
        client=("203.0.113.10", 50001),
    )
    login_form = public.get("/web/auth/login")
    assert login_form.status_code == 200, login_form.text
    login = public.post(
        "/web/auth/login",
        data={
            "pairing_code": pairing.json()["pairing_code"],
            "device_name": "A1 Web Browser",
            "csrf_token": _html_form_value(login_form.text, "csrf_token"),
        },
        headers={"Origin": _PUBLIC_WEB_ORIGIN},
        follow_redirects=False,
    )
    assert login.status_code == 303, login.text
    cookie = login.headers["set-cookie"].split(f"{SESSION_COOKIE_NAME}=", 1)[1].split(";", 1)[0]
    assert public.cookies.get(SESSION_COOKIE_NAME) == cookie
    return public, {"Origin": _PUBLIC_WEB_ORIGIN}


def _assert_uploaded_expense_detail(client: TestClient, *, identity, expense_id: int) -> None:
    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == expense_id


def _assert_uploaded_expense_pending_row(client: TestClient, *, identity, expense_id: int) -> None:
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(expense for expense in pending.json() if expense["id"] == expense_id)
    assert item["amount_cents"] is None
    UUID(item["public_id"])
    assert item["category"] == "其他"
    assert item["image_path"].startswith("uploads/")
    assert "\\" not in item["image_path"]
    assert item["image_hash"]


def _assert_uploaded_image_access_contract(client: TestClient, *, identity, expense_id: int) -> None:
    image_without_token = client.get(f"/api/expenses/{expense_id}/image")
    assert image_without_token.status_code == 401
    assert image_without_token.json()["error"] == "invalid_token"

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 200
    assert image.content == PNG_BYTES

    thumbnail = client.get(f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers)
    assert thumbnail.status_code == 200
    assert thumbnail.content.startswith(b"\xff\xd8")


def _assert_upload_confirm_requires_amount(client: TestClient, *, identity, expense_id: int) -> None:
    response = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert response.status_code == 400
    assert response.json()["error"] == "amount_required"


def _complete_uploaded_expense_fields(client: TestClient, *, identity, expense_id: int) -> None:
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


def _confirm_completed_upload(client: TestClient, *, identity, expense_id: int) -> None:
    response = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


def _assert_confirmed_upload_surfaces(client: TestClient, *, identity) -> None:
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

    exported = client.get("/api/expenses/export.csv?month=2026-05&category=餐饮", headers=identity.app_headers)
    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert "美团外卖" in exported.text
    assert "public_id" in exported.text.splitlines()[0]
    assert "3680" in exported.text

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 3680


def test_upload_pending_image_and_confirm_flow(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)

    _assert_uploaded_expense_detail(client, identity=identity, expense_id=expense_id)
    _assert_uploaded_expense_pending_row(client, identity=identity, expense_id=expense_id)
    _assert_uploaded_image_access_contract(client, identity=identity, expense_id=expense_id)
    _assert_upload_confirm_requires_amount(client, identity=identity, expense_id=expense_id)
    _complete_uploaded_expense_fields(client, identity=identity, expense_id=expense_id)
    _confirm_completed_upload(client, identity=identity, expense_id=expense_id)
    _assert_confirmed_upload_surfaces(client, identity=identity)


def test_public_web_confirm_records_browser_account_and_device(
    client: TestClient, *, identity
) -> None:
    expense_id = upload_png(client, identity=identity)
    _complete_uploaded_expense_fields(client, identity=identity, expense_id=expense_id)
    public, session_headers = _open_public_web_session(client, identity=identity)
    try:
        form = public.get(
            f"/web/expenses/{expense_id}/edit?ledger_id=owner",
            headers=session_headers,
        )
        assert form.status_code == 200, form.text
        confirmed = public.post(
            f"/web/expenses/{expense_id}/confirm",
            headers=session_headers,
            data={
                "csrf_token": _html_form_value(form.text, "csrf_token"),
                "ledger_id": "owner",
                "expected_row_version": _html_form_value(
                    form.text,
                    "expected_row_version",
                ),
                "idempotency_key": _html_form_value(form.text, "idempotency_key"),
            },
            follow_redirects=False,
        )
        assert confirmed.status_code == 303, confirmed.text
    finally:
        public.close()

    timeline = client.get(
        f"/api/expenses/{expense_id}/revisions",
        headers=identity.app_headers,
    )
    assert timeline.status_code == 200, timeline.text
    revision = timeline.json()["items"][0]
    assert revision["actor_account_name"] == "我"
    assert revision["actor_device_name"] == "A1 Web Browser"


def test_thumbnail_materialization_preserves_occ_before_image_deletion(client: TestClient, *, identity) -> None:
    expense_id = upload_png(client, identity=identity)

    # Simulate a migrated row whose source image exists but whose derived cache
    # locator is absent. The token visible before GET must remain usable.
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.thumbnail_path = None
        db.commit()
        db.refresh(expense)
        before_row_version = expense.row_version
        before_updated_at = expense.updated_at

    thumbnail = client.get(f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers)
    assert thumbnail.status_code == 200

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.thumbnail_path is not None
        assert expense.row_version == before_row_version
        assert expense.updated_at == before_updated_at

    edit = client.patch(
        f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "note": "缩略图读取后仍可编辑",
            "expected_row_version": before_row_version,
        },
    )
    assert edit.status_code == 200, edit.text

    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.image_deleted_at = now_utc()
        db.commit()

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 404
    thumbnail = client.get(f"/api/expenses/{expense_id}/thumbnail", headers=identity.app_headers)
    assert thumbnail.status_code == 404


def test_confirm_removes_expense_from_pending_and_adds_confirmed(
    client: TestClient,
    *,
    identity,
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

    response = confirm_expense_api(client, expense_id, headers=identity.app_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    assert all(item["id"] != expense_id for item in pending.json())

    confirmed = client.get("/api/expenses/confirmed?month=2026-05", headers=identity.app_headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["total"] == 1
    assert confirmed.json()["items"][0]["id"] == expense_id

    stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200
    assert stats.json()["total_amount_cents"] == 1851


@pytest.mark.real_db
def test_confirm_delete_after_confirm_hides_image_and_thumbnail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    from app.services import cleanup_service

    settings = cleanup_service.get_settings()
    monkeypatch.setattr(
        cleanup_service,
        "get_settings",
        lambda: replace(settings, delete_image_after_confirm=True),
    )
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")

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

    response = confirm_expense_api(client, expense_id, headers=identity.app_headers)
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
    assert confirm_expense_api(client, expense_id, headers=identity.app_headers).status_code == 200

    detail = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200
    for path_key in ["image_path", "thumbnail_path"]:
        relative_path = detail.json().get(path_key)
        if relative_path:
            (BACKEND_ROOT / relative_path).unlink(missing_ok=True)

    detail_after_delete = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail_after_delete.status_code == 200
    payload = detail_after_delete.json()
    assert payload["status"] == "confirmed"
    assert payload["amount_cents"] == 3680
    assert payload["merchant"] == "图片已清理商家"

    image = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert image.status_code == 404
    assert image.json()["error"] == "image_not_found"

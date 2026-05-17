"""v0.5 viewer write guards for API and /web direct POST entry points."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import AuthToken, Expense, LedgerMember
from app.routes.web_app import _require_local as _web_require_local
from app.services.identity_service import hash_secret
from app.services.time_service import now_utc
from conftest import PNG_BYTES, admin_headers, app_headers


VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_family_ledger(client: TestClient) -> str:
    response = client.post("/api/ledgers", headers=admin_headers(), json={"name": "viewer-guard"})
    assert response.status_code == 201, response.json()
    return response.json()["ledger_id"]


def _switch_to(client: TestClient, ledger_id: str) -> str:
    response = client.post(f"/api/ledgers/{ledger_id}/switch", headers=app_headers())
    assert response.status_code == 200, response.json()
    return response.json()["session_token"]


def _mint_invite(client: TestClient, ledger_id: str, owner_token: str, role: str) -> str:
    response = client.post(
        f"/api/ledgers/{ledger_id}/invitations",
        headers=_bearer(owner_token),
        json={"role": role},
    )
    assert response.status_code == 201, response.json()
    return response.json()["invite_token"]


def _make_role_token(client: TestClient, role: str) -> tuple[str, str, str]:
    ledger_id = _create_family_ledger(client)
    owner_token = _switch_to(client, ledger_id)
    invite = _mint_invite(client, ledger_id, owner_token, role)
    response = client.post(
        "/api/invitations/accept",
        json={
            "invite_token": invite,
            "account_name": f"user-{role}",
            "device_name": f"device-{role}",
            "platform": "android",
        },
    )
    assert response.status_code == 200, response.json()
    return ledger_id, owner_token, response.json()["session_token"]


def _make_web_ledger_with_role(client: TestClient, role: str) -> str:
    response = client.post("/api/ledgers", headers=admin_headers(), json={"name": f"web-{role}"})
    assert response.status_code == 201, response.json()
    ledger_id = response.json()["ledger_id"]
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == ledger_id).limit(1))
        assert member is not None
        member.role = role
        db.commit()
    return ledger_id


def _insert_confirmed_expense(ledger_id: str, merchant: str = "Viewer Export Cafe") -> None:
    now = now_utc()
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id=ledger_id,
                amount_cents=850,
                merchant=merchant,
                category="餐饮",
                note="",
                source="test",
                status="confirmed",
                created_at=now,
                updated_at=now,
                confirmed_at=now,
            )
        )
        db.commit()


def _assert_permission_denied(response, *, label: str) -> None:
    assert response.status_code == 403, label
    payload = response.json()
    assert payload["error"] == "permission_denied", label
    assert payload["message"] == VIEWER_WRITE_MESSAGE, label


def test_viewer_cannot_upload_android_screenshot(client: TestClient) -> None:
    _, _, viewer_token = _make_role_token(client, "viewer")

    response = client.post(
        "/api/app/upload-screenshot",
        headers=_bearer(viewer_token),
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )

    _assert_permission_denied(response, label="android screenshot upload")


def test_viewer_cannot_mutate_rules_or_apply_pending(client: TestClient) -> None:
    _, owner_token, viewer_token = _make_role_token(client, "viewer")
    created = client.post(
        "/api/rules/categories",
        headers=_bearer(owner_token),
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert created.status_code == 200, created.json()
    rule_id = created.json()["id"]

    checks = [
        (
            "create rule",
            client.post(
                "/api/rules/categories",
                headers=_bearer(viewer_token),
                json={"keyword": "Kimi", "category": "AI订阅", "enabled": True, "priority": 1},
            ),
        ),
        (
            "update rule",
            client.patch(
                f"/api/rules/categories/{rule_id}",
                headers=_bearer(viewer_token),
                json={"enabled": False},
            ),
        ),
        (
            "delete rule",
            client.delete(f"/api/rules/categories/{rule_id}", headers=_bearer(viewer_token)),
        ),
        (
            "apply pending",
            client.post("/api/rules/apply-pending", headers=_bearer(viewer_token)),
        ),
        (
            "confirmed batch update",
            client.post(
                "/api/expenses/confirmed/batch-update",
                headers=_bearer(viewer_token),
                json={"expense_ids": [999], "category": "餐饮"},
            ),
        ),
    ]
    for label, response in checks:
        _assert_permission_denied(response, label=label)


def test_web_viewer_direct_post_write_entries_are_rejected(web_client: TestClient) -> None:
    ledger_id = _make_web_ledger_with_role(web_client, "viewer")
    import_payload = json.dumps(
        [
            {
                "amount_cents": 850,
                "merchant": "Cafe",
                "category": "餐饮",
                "note": "",
                "expense_time": None,
                "tags": "",
                "source": "CSV导入",
            }
        ],
        ensure_ascii=False,
    )
    import_preview = web_client.post(
        "/web/import/preview",
        data={"ledger_id": ledger_id},
        files={"csv_file": ("rows.csv", b"amount_yuan,merchant\n1.00,Cafe\n", "text/csv")},
        follow_redirects=False,
    )
    _assert_permission_denied(import_preview, label="csv import preview")

    requests = [
        (
            "expense save",
            "/web/expenses/999/save",
            {"ledger_id": ledger_id, "amount_yuan": "8.50", "merchant": "Cafe", "category": "餐饮"},
        ),
        ("expense confirm", "/web/expenses/999/confirm", {"ledger_id": ledger_id}),
        ("expense reject", "/web/expenses/999/reject", {"ledger_id": ledger_id}),
        (
            "bulk review",
            "/web/review/bulk",
            {"ledger_id": ledger_id, "action": "confirm_ready", "expense_ids": ["999"]},
        ),
        (
            "pending batch reject",
            "/web/pending/batch-reject",
            {"ledger_id": ledger_id, "expense_ids": ["999"]},
        ),
        (
            "confirmed batch update",
            "/web/confirmed/batch-update",
            {"ledger_id": ledger_id, "action": "set_category", "expense_ids": ["999"], "category": "餐饮"},
        ),
        (
            "rules create",
            "/web/rules/create",
            {"ledger_id": ledger_id, "keyword": "Kimi", "category": "AI订阅", "priority": "1"},
        ),
        ("rules toggle", "/web/rules/999/toggle", {"ledger_id": ledger_id}),
        ("rules delete", "/web/rules/999/delete", {"ledger_id": ledger_id}),
        ("rules apply pending", "/web/rules/apply-pending", {"ledger_id": ledger_id}),
        ("rules apply confirmed", "/web/rules/apply-confirmed", {"ledger_id": ledger_id, "preview_confirmed": "yes"}),
        (
            "rules rollback",
            "/web/rules/applications/missing/rollback",
            {"ledger_id": ledger_id},
        ),
        (
            "merchant alias create",
            "/web/merchants/aliases/create",
            {"ledger_id": ledger_id, "canonical_merchant": "星巴克", "alias": "STARBUCKS"},
        ),
        ("merchant alias toggle", "/web/merchants/aliases/missing/toggle", {"ledger_id": ledger_id}),
        ("merchant alias delete", "/web/merchants/aliases/missing/delete", {"ledger_id": ledger_id}),
        (
            "csv import confirm",
            "/web/import/confirm",
            {"ledger_id": ledger_id, "payload": import_payload},
        ),
        ("csv import apply", "/web/import/missing/apply", {"ledger_id": ledger_id, "batch_size": "1"}),
        (
            "uncategorized bulk set",
            "/web/categories/uncategorized/bulk-set",
            {"ledger_id": ledger_id, "expense_ids": ["999"], "category": "餐饮"},
        ),
        ("duplicate keep", "/web/duplicates/999/keep", {"ledger_id": ledger_id}),
        ("duplicate reject current", "/web/duplicates/999/reject-current", {"ledger_id": ledger_id}),
        ("duplicate reject original", "/web/duplicates/999/reject-original", {"ledger_id": ledger_id}),
    ]

    for label, path, data in requests:
        response = web_client.post(path, data=data, follow_redirects=False)
        _assert_permission_denied(response, label=label)


def test_viewer_can_export_confirmed_csv_from_api_and_web(web_client: TestClient) -> None:
    ledger_id, _, viewer_token = _make_role_token(web_client, "viewer")
    _insert_confirmed_expense(ledger_id)

    api_export = web_client.get(
        "/api/expenses/export.csv",
        headers=_bearer(viewer_token),
    )
    assert api_export.status_code == 200, api_export.text
    assert api_export.headers["content-type"].startswith("text/csv")
    assert "Viewer Export Cafe" in api_export.text

    web_export = web_client.get(f"/web/export.csv?ledger_id={ledger_id}")
    assert web_export.status_code == 200, web_export.text
    assert web_export.headers["content-type"].startswith("text/csv")
    assert "Viewer Export Cafe" in web_export.text


def test_role_change_to_viewer_blocks_existing_token_writes(client: TestClient) -> None:
    ledger_id, owner_token, member_token = _make_role_token(client, "member")
    with SessionLocal() as db:
        token_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(member_token)))
        assert token_row is not None
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.account_id == token_row.account_id)
        )
        assert member is not None
        member_id = member.id

    changed = client.post(
        f"/api/ledgers/{ledger_id}/members/{member_id}/role",
        headers=_bearer(owner_token),
        json={"role": "viewer"},
    )
    assert changed.status_code == 200, changed.json()

    response = client.post(
        "/api/app/upload-screenshot",
        headers=_bearer(member_token),
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    _assert_permission_denied(response, label="demoted token android upload")

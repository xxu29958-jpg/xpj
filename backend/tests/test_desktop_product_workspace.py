"""Backend-owned Desktop projection and Inbox command contracts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from _desktop_product_test_support import (
    BRIDGE_HEADERS as _BRIDGE_HEADERS,
)
from _desktop_product_test_support import (
    WORKSPACES as _WORKSPACES,
)
from _desktop_product_test_support import (
    allow_testclient_loopback as _allow_testclient_loopback,
)
from _desktop_product_test_support import (
    command as _command,
)
from _desktop_product_test_support import (
    mint_desktop_token_from as _mint_desktop_token_from,
)
from _desktop_product_test_support import (
    principal_headers as _principal_headers,
)
from _desktop_product_test_support import (
    seed_expenses as _seed_expenses,
)
from _desktop_product_test_support import (
    workspace as _workspace,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.services._desktop_product_labels as desktop_product_labels
from app.database import SessionLocal
from app.models import Expense
from app.routes import desktop_product as desktop_product_routes
from app.schemas._desktop_product import (
    DesktopWorkspaceResponse,
)
from app.services.desktop_product_command_service import (
    execute_desktop_inbox_command,
)
from app.services.desktop_product_identity_service import revoke_desktop_app_session
from app.services.desktop_product_service import build_desktop_workspace
from app.services.time_service import now_utc


def test_desktop_routes_delegate_and_projection_labels_are_closed() -> None:
    assert desktop_product_routes.build_desktop_workspace is build_desktop_workspace
    assert desktop_product_routes.execute_desktop_inbox_command is execute_desktop_inbox_command
    assert desktop_product_routes.revoke_desktop_app_session is revoke_desktop_app_session
    cases = (
        (
            desktop_product_labels._debt_kind_label,
            {"unspecified": "未分类", "revolving": "循环周转", "installment": "分期还款", "one_off": "一次性借款"},
            "未分类",
        ),
        (
            desktop_product_labels._goal_progress_label,
            {
                "not_started": "未开始",
                "on_track": "正常",
                "near_limit": "接近上限",
                "over_limit": "已超限",
                "archived": "已归档",
            },
            "进度待确认",
        ),
        (
            desktop_product_labels._goal_status_label,
            {"active": "生效中", "archived": "已归档"},
            "状态待确认",
        ),
        (
            desktop_product_labels._income_source_label,
            {"salary": "工资", "bonus": "奖金", "freelance": "副业 / 接单", "rental": "租金", "other": "其它"},
            "其它",
        ),
        (
            desktop_product_labels._income_frequency_label,
            {"monthly": "每月固定", "one_time": "实际到账"},
            "到账安排待确认",
        ),
    )
    for labeler, expected, fallback in cases:
        assert {wire: labeler(wire) for wire in expected} == expected
        assert labeler("future_internal_enum") == labeler(None) == fallback


def test_desktop_projection_serves_real_pending_and_confirmed_rows(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    _allow_testclient_loopback(monkeypatch)
    pending_id, confirmed_id = _seed_expenses()
    desktop_token = _mint_desktop_token_from(identity.app_token)

    inbox = _workspace(client, "inbox", token=desktop_token).json()
    transactions = _workspace(
        client,
        "transactions",
        token=desktop_token,
    ).json()
    pending = next(row for row in inbox["rows"] if row["key"] == f"expense:{pending_id}")
    confirmed = next(row for row in transactions["rows"] if row["key"] == f"expense:{confirmed_id}")

    assert inbox["workspace"] == "inbox"
    assert pending["title"] == "真实收件商家"
    assert pending["amount_minor"] == 1880
    assert pending["status"] == "pending"
    assert pending["capabilities"] == ["save", "confirm", "ignore"]
    assert pending["edit"] == {
        "expected_row_version": 1,
        "amount_minor": 1880,
        "currency_code": "CNY",
        "currency_symbol": "¥",
        "minor_unit_digits": 2,
        "home_amount_minor": 1880,
        "home_currency_code": "CNY",
        "original_amount_minor": 1880,
        "original_currency_code": "CNY",
        "exchange_rate_to_home": None,
        "exchange_rate_date": None,
        "exchange_rate_source": "base",
        "fx_status": "ready",
        "merchant": "真实收件商家",
        "category": "餐饮",
    }
    assert pending["occurred_precision"] == "instant"
    assert all(field["label"] != "并发版本" for field in pending["fields"])
    assert transactions["workspace"] == "transactions"
    assert confirmed["title"] == "真实流水商家"
    assert confirmed["amount_minor"] == 2600
    assert confirmed["status"] == "confirmed"
    assert confirmed["capabilities"] == []
    assert confirmed["edit"] is None


def test_each_desktop_domain_uses_one_bounded_workspace_record_contract(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    _allow_testclient_loopback(monkeypatch)
    desktop_token = _mint_desktop_token_from(identity.app_token)

    for workspace in _WORKSPACES:
        response = _workspace(client, workspace, token=desktop_token)
        assert response.status_code == 200
        payload = response.json()
        contract = DesktopWorkspaceResponse.model_validate(payload)
        assert payload["workspace"] == workspace
        assert contract.workspace == workspace
        assert payload["ledger_id"] == "owner"
        assert payload["ledger_name"] == "我的小票夹"
        assert isinstance(payload["rows"], list)
        assert isinstance(payload["ledgers"], list)
        assert payload["total_count"] >= len(payload["rows"])
        assert len(payload["rows"]) <= 200
        for row in payload["rows"]:
            assert set(row) == {
                "key",
                "kind",
                "title",
                "subtitle",
                "status",
                "status_label",
                "amount_minor",
                "currency_code",
                "value_text",
                "occurred_at",
                "occurred_precision",
                "fields",
                "capabilities",
                "edit",
            }


def test_desktop_inbox_save_confirm_and_same_key_replay_are_atomic(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    _allow_testclient_loopback(monkeypatch)
    pending_id, _ = _seed_expenses()
    desktop_token = _mint_desktop_token_from(identity.app_token)

    saved = _command(
        client,
        pending_id,
        key="desktop-save-1",
        token=desktop_token,
        body={
            "action": "save",
            "expected_row_version": 1,
            "original_amount_minor": 1900,
            "original_currency_code": "CNY",
            "home_amount_minor": 1880,
            "home_currency_code": "CNY",
            "exchange_rate_to_home": None,
            "exchange_rate_date": None,
            "exchange_rate_source": "base",
            "fx_status": "ready",
            "merchant": "修正后的商家",
            "category": "日用",
        },
    )
    assert saved.status_code == 200
    saved_payload = saved.json()
    assert saved_payload["action"] == "save"
    assert saved_payload["expense_status"] == "pending"
    assert saved_payload["row_version"] > 1

    confirm_body = {
        "action": "confirm",
        "expected_row_version": saved_payload["row_version"],
    }
    confirmed = _command(
        client,
        pending_id,
        key="desktop-confirm-1",
        token=desktop_token,
        body=confirm_body,
    )
    replay = _command(
        client,
        pending_id,
        key="desktop-confirm-1",
        token=desktop_token,
        body=confirm_body,
    )

    assert confirmed.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == confirmed.json()
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.public_id == pending_id))
        assert expense is not None
        assert expense.amount_cents == 1900
        assert expense.merchant == "修正后的商家"
        assert expense.category == "日用"
        assert expense.status == "confirmed"
        assert expense.row_version == confirmed.json()["row_version"]


def _seed_foreign_expense(
    *,
    public_id: str,
    frozen_rate: Decimal,
    frozen_date: date,
) -> None:
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                public_id=public_id,
                amount_cents=87_938,
                home_currency_code="CNY",
                original_currency_code="USD",
                original_amount_minor=12_345,
                exchange_rate_to_cny=frozen_rate,
                exchange_rate_date=frozen_date,
                exchange_rate_source="manual",
                fx_status="ready",
                merchant="外币商家",
                category="餐饮",
                source="pytest-desktop-fx",
                status="pending",
                created_at=now_utc(),
                updated_at=now_utc(),
            )
        )
        db.commit()


def _assert_foreign_expense(
    *,
    public_id: str,
    merchant: str,
    status: str,
    amount_cents: int,
    original_amount_minor: int,
    frozen_rate: Decimal,
    frozen_date: date,
) -> None:
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.public_id == public_id))
        assert expense is not None
        assert expense.merchant == merchant
        assert expense.status == status
        assert expense.amount_cents == amount_cents
        assert expense.home_currency_code == "CNY"
        assert expense.original_currency_code == "USD"
        assert expense.original_amount_minor == original_amount_minor
        assert expense.exchange_rate_to_cny == frozen_rate
        assert expense.exchange_rate_date == frozen_date
        assert expense.exchange_rate_source == "manual"
        assert expense.fx_status == "ready"


def _assert_foreign_edit_snapshot(edit: dict[str, object]) -> None:
    assert edit["amount_minor"] == 12_345
    assert edit["currency_code"] == "USD"
    assert edit["home_amount_minor"] == 87_938
    assert edit["home_currency_code"] == "CNY"
    assert edit["original_amount_minor"] == 12_345
    assert edit["original_currency_code"] == "USD"
    assert edit["exchange_rate_to_home"] == "7.12340000"
    assert edit["exchange_rate_date"] == "2026-05-04"
    assert edit["exchange_rate_source"] == "manual"
    assert edit["fx_status"] == "ready"


def _foreign_edit(client: TestClient, *, public_id: str, token: str) -> dict[str, object]:
    inbox = _workspace(client, "inbox", token=token).json()
    row = next(item for item in inbox["rows"] if item["key"] == f"expense:{public_id}")
    return row["edit"]


def test_desktop_foreign_inbox_edits_preserve_frozen_fx_snapshot(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    _allow_testclient_loopback(monkeypatch)
    desktop_token = _mint_desktop_token_from(identity.app_token)
    public_id = str(uuid4())
    frozen_rate = Decimal("7.12340000")
    frozen_date = date(2026, 5, 4)
    _seed_foreign_expense(
        public_id=public_id,
        frozen_rate=frozen_rate,
        frozen_date=frozen_date,
    )

    edit = _foreign_edit(client, public_id=public_id, token=desktop_token)
    _assert_foreign_edit_snapshot(edit)

    merchant_only = _command(
        client,
        public_id,
        key="desktop-fx-merchant",
        token=desktop_token,
        body={
            "action": "save",
            "expected_row_version": edit["expected_row_version"],
            "merchant": "仅修改商家",
        },
    )
    assert merchant_only.status_code == 200
    _assert_foreign_expense(
        public_id=public_id,
        merchant="仅修改商家",
        status="pending",
        amount_cents=87_938,
        original_amount_minor=12_345,
        frozen_rate=frozen_rate,
        frozen_date=frozen_date,
    )

    amount_edit = _command(
        client,
        public_id,
        key="desktop-fx-amount",
        token=desktop_token,
        body={
            "action": "save",
            "expected_row_version": merchant_only.json()["row_version"],
            "original_amount_minor": 12_346,
            "original_currency_code": edit["original_currency_code"],
            "home_amount_minor": edit["home_amount_minor"],
            "home_currency_code": edit["home_currency_code"],
            "exchange_rate_to_home": edit["exchange_rate_to_home"],
            "exchange_rate_date": edit["exchange_rate_date"],
            "exchange_rate_source": edit["exchange_rate_source"],
            "fx_status": edit["fx_status"],
        },
    )
    assert amount_edit.status_code == 200
    confirmed = _command(
        client,
        public_id,
        key="desktop-fx-confirm",
        token=desktop_token,
        body={
            "action": "confirm",
            "expected_row_version": amount_edit.json()["row_version"],
        },
    )
    assert confirmed.status_code == 200
    _assert_foreign_expense(
        public_id=public_id,
        merchant="仅修改商家",
        status="confirmed",
        amount_cents=87_945,
        original_amount_minor=12_346,
        frozen_rate=frozen_rate,
        frozen_date=frozen_date,
    )


def test_desktop_inbox_ignore_requires_idempotency_and_rejects_stale_occ(
    client: TestClient,
    monkeypatch,
    identity,
) -> None:
    _allow_testclient_loopback(monkeypatch)
    pending_id, _ = _seed_expenses()
    desktop_token = _mint_desktop_token_from(identity.app_token)
    body = {"action": "ignore", "expected_row_version": 1}
    route = f"/desktop/workspaces/inbox/expenses/{pending_id}/commands"

    unauthenticated = client.post(
        route,
        headers={
            **_BRIDGE_HEADERS,
            "Idempotency-Key": "desktop-ignore-no-auth",
        },
        json=body,
    )
    missing_key = _command(
        client,
        pending_id,
        key=None,
        token=desktop_token,
        body=body,
    )
    stale = _command(
        client,
        pending_id,
        key="desktop-ignore-stale",
        token=desktop_token,
        body={"action": "ignore", "expected_row_version": 99},
    )
    ignored = client.post(
        route,
        headers={
            **_principal_headers(desktop_token),
            "Idempotency-Key": "desktop-ignore-1",
        },
        json=body,
    )

    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"] == "invalid_token"
    assert missing_key.status_code == 422
    assert missing_key.json()["error"] == "idempotency_key_required"
    assert stale.status_code == 409
    assert stale.json()["error"] == "state_conflict"
    assert ignored.status_code == 200
    assert ignored.json()["action"] == "ignore"
    assert ignored.json()["expense_status"] == "rejected"

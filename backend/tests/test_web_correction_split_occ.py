"""Web composite correction keeps split facts behind the parent OCC boundary."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, LedgerMember
from app.routes import web_expense_correction as correction_route
from app.schemas import ExpenseCorrectionRequest, ExpenseSplitRequest
from app.services.expense_correction_service import correct_expense
from app.services.expense_service import get_expense


def _owner_member_id() -> int:
    with SessionLocal() as db:
        member_id = db.scalar(
            select(LedgerMember.id)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
    assert member_id is not None
    return int(member_id)


def _create_expense_with_split(web_client: TestClient, identity: object) -> tuple[int, dict, dict]:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "拆账 OCC 测试",
            "category": "餐饮",
            "expense_time": "2026-05-04T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = int(created.json()["id"])
    seeded = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": "seed-web-split-occ"},
        json={
            "expected_row_version": created.json()["row_version"],
            "reason": "补入初始拆账",
            "splits": [{"member_id": _owner_member_id(), "amount_cents": 500, "note": "初始"}],
        },
    )
    assert seeded.status_code == 201, seeded.text
    splits = web_client.get(f"/api/expenses/{expense_id}/splits", headers=identity.app_headers)
    assert splits.status_code == 200, splits.text
    split = splits.json()["splits"][0]
    correction_page = web_client.get(f"/web/expenses/{expense_id}/correct?ledger_id=owner")
    assert correction_page.status_code == 200, correction_page.text
    assert f'name="split_public_id" value="{split["public_id"]}"' in correction_page.text
    return expense_id, seeded.json(), split


def _replace_split_in_peer_transaction(expense_id: int, member_id: int) -> None:
    with SessionLocal() as db:
        current = get_expense(db, expense_id, "owner")
        actor_account_id = db.scalar(select(Account.id).order_by(Account.id.asc()).limit(1))
        assert actor_account_id is not None
        correct_expense(
            db,
            expense_id=expense_id,
            tenant_id="owner",
            payload=ExpenseCorrectionRequest(
                expected_row_version=current.row_version,
                reason="parse 后的并发更正",
                note="parse 后的最新备注",
                splits=[
                    ExpenseSplitRequest(
                        member_id=member_id,
                        amount_cents=700,
                        note="parse 后的最新拆账",
                    )
                ],
            ),
            actor_account_id=actor_account_id,
            actor_device_id=None,
            idempotency_key="peer-between-parse-and-cas",
        )


def _change_scalar_in_peer_transaction(expense_id: int) -> None:
    with SessionLocal() as db:
        current = get_expense(db, expense_id, "owner")
        actor_account_id = db.scalar(select(Account.id).order_by(Account.id.asc()).limit(1))
        assert actor_account_id is not None
        correct_expense(
            db,
            expense_id=expense_id,
            tenant_id="owner",
            payload=ExpenseCorrectionRequest(
                expected_row_version=current.row_version,
                reason="parse 后的并发标量更正",
                note="parse 后的最新备注",
            ),
            actor_account_id=actor_account_id,
            actor_device_id=None,
            idempotency_key="peer-scalar-between-parse-and-cas",
        )


def test_web_correction_rejects_stale_split_rows_before_scalar_retry(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id, seeded, old_split = _create_expense_with_split(web_client, identity)
    concurrent = web_client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": "concurrent-web-split-occ"},
        json={
            "expected_row_version": seeded["expense"]["row_version"],
            "reason": "另一端调整拆账",
            "note": "并发后的备注",
            "splits": [
                {"member_id": old_split["member_id"], "amount_cents": 600, "note": "并发后的事实"}
            ],
        },
    )
    assert concurrent.status_code == 201, concurrent.text

    stale_form = {
        "ledger_id": "owner",
        "reason": "旧页面只想修正商家",
        "merchant": "修正后的商家",
        "note": "旧页面备注",
        "expected_row_version": str(seeded["expense"]["row_version"]),
        "idempotency_key": "web-split-occ-retry",
        "split_public_id": old_split["public_id"],
        "split_member_id": str(old_split["member_id"]),
        "split_amount_yuan": "5.00",
        "split_note": "初始",
    }
    conflict = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data=stale_form,
        follow_redirects=False,
    )
    assert conflict.status_code == 409, conflict.text
    note_position = conflict.text.index('name="note"')
    assert "并发后的备注" in conflict.text, conflict.text[note_position : note_position + 300]
    assert "旧页面备注" not in conflict.text

    stale_form["expected_row_version"] = str(concurrent.json()["expense"]["row_version"])
    stale_retry = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data=stale_form,
        follow_redirects=False,
    )
    assert stale_retry.status_code == 409, stale_retry.text
    assert "拆账已在其它端变化" in stale_retry.text

    current = web_client.get(f"/api/expenses/{expense_id}/splits", headers=identity.app_headers)
    assert current.status_code == 200, current.text
    assert current.json()["splits"][0]["amount_cents"] == 600
    assert current.json()["splits"][0]["note"] == "并发后的事实"

    current_split = current.json()["splits"][0]
    recovery = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            **stale_form,
            "expected_row_version": str(current.json()["row_version"]),
            "split_public_id": current_split["public_id"],
            "split_amount_yuan": "6.00",
            "split_note": "并发后的事实",
            "note": "并发后的备注",
        },
        follow_redirects=False,
    )
    assert recovery.status_code == 303, recovery.text
    recovered = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["merchant"] == "修正后的商家"
    assert recovered.json()["note"] == "并发后的备注"


@pytest.mark.real_db
def test_command_conflict_renders_split_replaced_after_parse(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    expense_id, seeded, old_split = _create_expense_with_split(web_client, identity)
    original_execute = correction_route.execute_correction

    def execute_after_peer_change(db, **kwargs):
        _replace_split_in_peer_transaction(expense_id, old_split["member_id"])
        return original_execute(db, **kwargs)

    monkeypatch.setattr(correction_route, "execute_correction", execute_after_peer_change)
    conflict = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "只想改商家",
            "merchant": "我的更正",
            "expected_row_version": str(seeded["expense"]["row_version"]),
            "idempotency_key": "web-late-child-race",
            "split_public_id": old_split["public_id"],
            "split_member_id": str(old_split["member_id"]),
            "split_amount_yuan": "5.00",
            "split_note": "初始",
        },
        follow_redirects=False,
    )
    assert conflict.status_code == 409, conflict.text
    current = web_client.get(f"/api/expenses/{expense_id}/splits", headers=identity.app_headers)
    current_split = current.json()["splits"][0]
    assert f'value="{current_split["public_id"]}"' in conflict.text
    assert f'value="{old_split["public_id"]}"' not in conflict.text
    assert "parse 后的最新拆账" in conflict.text


@pytest.mark.real_db
def test_command_conflict_preserves_split_intent_when_identity_is_unchanged(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    expense_id, seeded, split = _create_expense_with_split(web_client, identity)
    original_execute = correction_route.execute_correction

    def execute_after_peer_change(db, **kwargs):
        _change_scalar_in_peer_transaction(expense_id)
        return original_execute(db, **kwargs)

    monkeypatch.setattr(correction_route, "execute_correction", execute_after_peer_change)
    conflict = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "保留我的拆账输入",
            "merchant": "我的商家更正",
            "expected_row_version": str(seeded["expense"]["row_version"]),
            "idempotency_key": "web-late-scalar-race",
            "split_public_id": split["public_id"],
            "split_member_id": str(split["member_id"]),
            "split_amount_yuan": "8.88",
            "split_note": "用户未提交的拆账",
        },
        follow_redirects=False,
    )
    assert conflict.status_code == 409, conflict.text
    assert f'value="{split["public_id"]}"' in conflict.text
    assert 'name="split_amount_yuan" value="8.88"' in conflict.text
    assert 'name="split_note" value="用户未提交的拆账"' in conflict.text
    assert "parse 后的最新备注" in conflict.text
    assert "拆账已在其它端变化" not in conflict.text

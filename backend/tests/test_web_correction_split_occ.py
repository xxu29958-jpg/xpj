"""Web composite correction keeps split facts behind the parent OCC boundary."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember


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

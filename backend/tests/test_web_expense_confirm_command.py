"""Root contracts for the Web save-and-confirm transaction command."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense
from app.routes._web_expense_edit_command import prepare_web_expense_form
from app.schemas import ExpenseUpdateRequest
from app.services.expense_review_command_service import confirm_expense_submission
from app.services.expense_service import update_expense
from tests._web_bulk_test_support import seed_pending_with_amount
from tests.test_web_transactions_backend import _expense_payload


def _save_confirm_data(before: dict) -> dict[str, str]:
    return {
        "ledger_id": "owner",
        "expected_row_version": str(before["row_version"]),
        "idempotency_key": str(uuid4()),
        "save_before_confirm": "1",
        "original_currency": "CNY",
        "amount_yuan": "12.34",
        "merchant": "Saved Then Confirmed",
        "category": "餐饮",
        "note": "权威表单",
        "tags": "家庭",
    }


def _prepare_save_confirm_payload(
    expense_id: int,
    before: dict,
    data: dict[str, str],
) -> ExpenseUpdateRequest:
    with SessionLocal() as db:
        payload, prepared = prepare_web_expense_form(
            db,
            expense_id=expense_id,
            selected_ledger_id="owner",
            expected_row_version=str(before["row_version"]),
            idempotency_key=data["idempotency_key"],
            amount_yuan=data["amount_yuan"],
            original_currency="CNY",
            merchant=data["merchant"],
            category=data["category"],
            note=data["note"],
            tags=data["tags"],
            expense_time=None,
        )
        assert payload is not None, prepared
        db.rollback()
        return payload


def _confirmation_intent(data: dict[str, str]) -> dict[str, object]:
    fields = {"amount_yuan", "merchant", "category", "note", "tags"}
    return {
        "save_before_confirm": True,
        **{key: data[key] for key in fields},
    }


def _assert_category_input_is_blank(
    web_client: TestClient,
    expense_id: int,
) -> None:
    for suffix in ("", "?fragment=1"):
        rendered = web_client.get(f"/web/expenses/{expense_id}/edit{suffix}")
        assert rendered.status_code == 200, rendered.text
        assert re.search(r'name="category"[^>]*value=""', rendered.text)


def test_save_confirm_replay_is_idempotent_but_changed_stale_intent_conflicts(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "10.00", "Before Confirm", identity=identity
    )
    before = _expense_payload(web_client, expense_id, identity=identity)
    data = _save_confirm_data(before)
    losing_data = {**data, "merchant": "Before Confirm", "idempotency_key": str(uuid4())}
    losing_payload = _prepare_save_confirm_payload(expense_id, before, losing_data)

    first = web_client.post(
        f"/web/expenses/{expense_id}/confirm", data=data, follow_redirects=False
    )
    assert first.status_code == 303, first.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after["status"] == "confirmed"
    assert after["amount_cents"] == 1234
    assert after["merchant"] == "Saved Then Confirmed"
    assert after["note"] == "权威表单"
    assert after["tags"] == "家庭"

    replay = web_client.post(
        f"/web/expenses/{expense_id}/confirm", data=data, follow_redirects=False
    )
    assert replay.status_code == 303, replay.text
    assert _expense_payload(web_client, expense_id, identity=identity) == after

    reused = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={**data, "merchant": "Different Stale Intent"},
        follow_redirects=False,
    )
    assert reused.status_code == 422, reused.text
    assert _expense_payload(web_client, expense_id, identity=identity) == after
    rotated_key = re.search(
        r'name="idempotency_key" value="([^"]+)"',
        reused.text,
    )
    assert rotated_key is not None
    assert rotated_key.group(1) != data["idempotency_key"]

    retried_new_intent = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            **data,
            "idempotency_key": rotated_key.group(1),
            "merchant": "Different Stale Intent",
        },
        follow_redirects=False,
    )
    assert retried_new_intent.status_code == 409, retried_new_intent.text
    assert "幂等键已被另一请求使用" not in retried_new_intent.text
    assert _expense_payload(web_client, expense_id, identity=identity) == after

    # Both payloads were prepared against the same pre-confirm snapshot. The
    # loser changed only amount/category while retaining the old merchant; the
    # winner reached the same amount/category but a different merchant. A
    # sparse-diff replay heuristic would falsely accept this. A fresh intent
    # key must instead reach OCC and conflict.
    with SessionLocal() as db, pytest.raises(AppError) as raised:
        confirm_expense_submission(
            db,
            expense_id=expense_id,
            tenant_id="owner",
            expected_row_version=before["row_version"],
            request_expected_row_version=before["row_version"],
            idempotency_key=losing_data["idempotency_key"],
            intent_body=_confirmation_intent(losing_data),
            update_payload=losing_payload,
        )
    assert raised.value.error == "state_conflict"
    assert _expense_payload(web_client, expense_id, identity=identity) == after


def _assert_unclassified_form_stays_unclassified(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "10.00", "No Category", identity=identity
    )
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.category = ""
        db.commit()
    before = _expense_payload(web_client, expense_id, identity=identity)

    _assert_category_input_is_blank(web_client, expense_id)

    data = {
        "ledger_id": "owner",
        "expected_row_version": str(before["row_version"]),
        "idempotency_key": str(uuid4()),
        "save_before_confirm": "1",
        "original_currency": "CNY",
        "amount_yuan": "10.00",
        "merchant": "No Category",
        "category": "",
        "note": "",
        "tags": "",
    }
    response = web_client.post(
        f"/web/expenses/{expense_id}/confirm", data=data, follow_redirects=False
    )
    assert response.status_code == 422, response.text
    after = _expense_payload(web_client, expense_id, identity=identity)
    assert after == before
    assert after["category"] == ""
    assert after["status"] == "pending"

    dirty = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={**data, "category": "未分类"},
        follow_redirects=False,
    )
    assert dirty.status_code == 422, dirty.text
    assert "请选择具体分类" in dirty.text
    assert _expense_payload(web_client, expense_id, identity=identity) == before

    with SessionLocal() as db:
        concurrent = update_expense(
            db,
            expense_id,
            "owner",
            ExpenseUpdateRequest(
                expected_row_version=before["row_version"],
                merchant="Concurrent Truth",
            ),
        )
        concurrent_version = concurrent.row_version

    stale_invalid = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={**data, "category": "未分类"},
        follow_redirects=False,
    )
    assert stale_invalid.status_code == 422, stale_invalid.text
    assert re.search(
        rf'name="expected_row_version" value="{before["row_version"]}"',
        stale_invalid.text,
    )

    stale_retry = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={**data, "category": "餐饮"},
        follow_redirects=False,
    )
    assert stale_retry.status_code == 409, stale_retry.text
    current = _expense_payload(web_client, expense_id, identity=identity)
    assert current["row_version"] == concurrent_version
    assert current["merchant"] == "Concurrent Truth"
    assert current["status"] == "pending"


def _assert_dirty_categories_allow_unrelated_save(
    web_client: TestClient,
    *,
    identity,
) -> None:
    for token in ("未分类", "未分類", "none", "null"):
        expense_id = seed_pending_with_amount(
            web_client, "10.00", f"Dirty {token}", identity=identity
        )
        with SessionLocal() as db:
            expense = db.get(Expense, expense_id)
            assert expense is not None
            expense.category = token
            db.commit()
        before = _expense_payload(web_client, expense_id, identity=identity)

        _assert_category_input_is_blank(web_client, expense_id)

        saved = web_client.post(
            f"/web/expenses/{expense_id}/save",
            data={
                "ledger_id": "owner",
                "expected_row_version": str(before["row_version"]),
                "original_currency": "CNY",
                "amount_yuan": "10.00",
                "merchant": f"Dirty {token}",
                "category": "",
                "note": "unrelated edit",
                "tags": "",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303, saved.text
        after = _expense_payload(web_client, expense_id, identity=identity)
        assert after["category"] == token
        assert after["note"] == "unrelated edit"


def _assert_invalid_token_preserves_full_form(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "10.00", "Persisted Merchant", identity=identity
    )
    before = _expense_payload(web_client, expense_id, identity=identity)
    data = {
        "ledger_id": "owner",
        "expected_row_version": "invalid-token",
        "idempotency_key": str(uuid4()),
        "save_before_confirm": "1",
        "original_currency": "CNY",
        "amount_yuan": "88.88",
        "merchant": "Submitted Merchant",
        "category": "餐饮",
        "note": "Submitted Note",
        "tags": "Submitted Tag",
        "expense_time": "2030-01-02T03:04",
    }
    for fragment in (0, 1):
        response = web_client.post(
            f"/web/expenses/{expense_id}/confirm",
            data={**data, "fragment": str(fragment)},
            follow_redirects=False,
        )
        assert response.status_code == 422, response.text
        for value in (
            "invalid-token",
            data["idempotency_key"],
            "88.88",
            "Submitted Merchant",
            "餐饮",
            "Submitted Note",
            "Submitted Tag",
            "2030-01-02T03:04",
        ):
            assert value in response.text
    assert _expense_payload(web_client, expense_id, identity=identity) == before


def _assert_save_conflict_preserves_submitted_snapshot(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = seed_pending_with_amount(
        web_client, "10.00", "Before Conflict", identity=identity
    )
    before = _expense_payload(web_client, expense_id, identity=identity)
    with SessionLocal() as db:
        concurrent = update_expense(
            db,
            expense_id,
            "owner",
            ExpenseUpdateRequest(
                expected_row_version=before["row_version"],
                merchant="Concurrent Truth",
            ),
        )
        concurrent_version = concurrent.row_version

    submitted = {
        "ledger_id": "owner",
        "expected_row_version": str(before["row_version"]),
        "original_currency": "CNY",
        "amount_yuan": "77.77",
        "merchant": "Submitted Stale",
        "category": "餐饮",
        "note": "Keep My Note",
        "tags": "Keep My Tag",
    }
    for fragment in (0, 1):
        response = web_client.post(
            f"/web/expenses/{expense_id}/save",
            data={**submitted, "fragment": str(fragment)},
            follow_redirects=False,
        )
        assert response.status_code == 409, response.text
        for value in (
            str(before["row_version"]),
            "77.77",
            "Submitted Stale",
            "餐饮",
            "Keep My Note",
            "Keep My Tag",
        ):
            assert value in response.text
    current = _expense_payload(web_client, expense_id, identity=identity)
    assert current["row_version"] == concurrent_version
    assert current["merchant"] == "Concurrent Truth"


def _assert_failed_confirmation_rolls_back_form_edits(
    web_client: TestClient,
    *,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 1000,
            "merchant": "Before Failed Confirm",
            "category": "餐饮",
            "expense_time": "2040-05-04T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = int(created.json()["id"])
    before = _expense_payload(web_client, expense_id, identity=identity)
    response = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(before["row_version"]),
            "idempotency_key": str(uuid4()),
            "save_before_confirm": "1",
            "original_currency": "USD",
            "amount_yuan": "10.00",
            "merchant": "Must Roll Back",
            "category": "餐饮",
            "note": "",
            "tags": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 409, response.text
    assert "汇率还没同步完成" in response.text
    assert _expense_payload(web_client, expense_id, identity=identity) == before


def test_save_confirm_preserves_unclassified_fact_and_rolls_back_failed_command(
    web_client: TestClient,
    *,
    identity,
) -> None:
    _assert_unclassified_form_stays_unclassified(web_client, identity=identity)
    _assert_dirty_categories_allow_unrelated_save(web_client, identity=identity)
    _assert_invalid_token_preserves_full_form(web_client, identity=identity)
    _assert_save_conflict_preserves_submitted_snapshot(web_client, identity=identity)
    _assert_failed_confirmation_rolls_back_form_edits(web_client, identity=identity)

"""Real PostgreSQL/HTTP continuation through older relationship facts."""

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from app.services.ledger_service import find_owner_account_id_for_ledger
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_debt_actions import _create_debt, _form, _headers


@pytest.mark.parametrize("role", ["member", "viewer"])
def test_visible_ledger_without_active_owner_keeps_relationship_history(web_client, identity, role):
    debt = _create_debt(web_client, identity=identity)
    public_id = debt["public_id"]
    adjusted = web_client.post(
        f"/web/debts/{public_id}/adjustments",
        data=_form(debt, idempotency_key="no-owner-history-adjustment",
                   amount_major="-50.00", reason="历史手续费更正"),
    )
    assert adjusted.status_code == 200, adjusted.text
    with SessionLocal() as db:
        membership = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        membership.role = role
        db.commit()
        assert find_owner_account_id_for_ledger(db, ledger_id="owner") is None

    page = web_client.get(f"/web/debts/{public_id}?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert "共 2 条" in page.text
    assert "建立往来" in page.text and "历史手续费更正" in page.text
    # Missing attribution cannot authorize another ledger's obligation.
    hidden = web_client.get(f"/web/debts/{public_id}?ledger_id=tester_1")
    assert hidden.status_code == 404


def test_older_repayment_page_can_be_reopened_voided_and_replayed(web_client, identity):
    debt = _create_debt(web_client, identity=identity)
    public_id = debt["public_id"]
    first_fact_id = None
    for _ in range(21):
        response = web_client.post(
            f"/api/debts/{public_id}/repayments", headers=_headers(identity),
            json={"amount_cents": 100, "expected_row_version": debt["row_version"]},
        )
        assert response.status_code == 201, response.text
        debt = response.json()
        first_fact_id = first_fact_id or debt["repayment_public_id"]

    newest = web_client.get(f"/web/debts/{public_id}?ledger_id=owner")
    assert newest.status_code == 200
    assert "共 22 条" in newest.text and "activity_page=2" in newest.text
    assert f'id="repayment-{first_fact_id}"' not in newest.text
    older = web_client.get(f"/web/debts/{public_id}?ledger_id=owner&activity_page=2")
    assert older.status_code == 200
    assert f'id="repayment-{first_fact_id}"' in older.text
    assert "建立往来" in older.text
    focused = web_client.get(f"/web/debts/{public_id}?ledger_id=owner&focus_repayment={first_fact_id}")
    assert focused.status_code == 200
    assert f'id="repayment-{first_fact_id}"' in focused.text and "第 2 页" in focused.text

    action = f"/web/debts/{public_id}/repayment-voids?activity_page=2"
    # The native form supplies the real key, CSRF and OCC fields.
    forms = hidden_post_forms(older.text)
    form = {**forms[action], "repayment_public_id": first_fact_id, "reason": ""}
    original_key = form["idempotency_key"]
    rejected = web_client.post(action, data=form)
    assert rejected.status_code == 422
    retained = hidden_post_forms(rejected.text)[action]
    assert retained["idempotency_key"] == original_key
    assert retained["repayment_public_id"] == first_fact_id
    assert "第 2 页" in rejected.text
    valid = {**retained, "reason": "重复记了这一笔"}
    saved = web_client.post(action, data=valid)
    replay = web_client.post(action, data=valid)
    assert saved.status_code == replay.status_code == 200
    assert "重复记了这一笔" in saved.text
    current = web_client.get(f"/api/debts/{public_id}/activity", headers=identity.app_headers)
    assert current.status_code == 200
    assert current.json()["total"] == 23
    assert sum(item["kind"] == "repayment_void" for item in current.json()["items"]) == 1


@pytest.mark.parametrize("target_kind", ["blank", "other_debt"])
def test_invalid_void_target_keeps_debt_error_page_and_original_form(web_client, identity, target_kind):
    debt = _create_debt(web_client, identity=identity)
    public_id = debt["public_id"]
    paid = web_client.post(
        f"/api/debts/{public_id}/repayments", headers=_headers(identity),
        json={"amount_cents": 100, "expected_row_version": debt["row_version"]},
    )
    assert paid.status_code == 201, paid.text
    debt = paid.json()
    target = ""
    if target_kind == "other_debt":
        other = _create_debt(web_client, identity=identity)
        paid = web_client.post(
            f"/api/debts/{other['public_id']}/repayments", headers=_headers(identity),
            json={"amount_cents": 100, "expected_row_version": other["row_version"]},
        )
        assert paid.status_code == 201, paid.text
        target = paid.json()["repayment_public_id"]

    action = f"/web/debts/{public_id}/repayment-voids"
    page = web_client.get(f"/web/debts/{public_id}?ledger_id=owner")
    form = hidden_post_forms(page.text)[action]
    rejected = web_client.post(action, data={
        **form, "ledger_id": "owner", "expected_row_version": str(debt["row_version"]),
        "repayment_public_id": target, "reason": "保留我的撤销说明",
    })

    assert rejected.status_code == (422 if target_kind == "blank" else 404)
    assert "往来历史" in rejected.text
    assert "保留我的撤销说明" in rejected.text
    assert 'id="debt-action-error-repayment_void"' in rejected.text
    retained = hidden_post_forms(rejected.text)[action]
    # The rejected target is retained as feedback, never reassigned to an
    # unrelated repayment. The user can still select the actual history row.
    assert retained["repayment_public_id"] == debt["repayment_public_id"]
    current = web_client.get(f"/api/debts/{public_id}", headers=identity.app_headers).json()
    assert current["row_version"] == debt["row_version"]
    assert current["paid_amount_cents"] == 100
    if target:
        # Direct navigation to a foreign repayment still rejects the focus.
        focused = web_client.get(f"/web/debts/{public_id}?ledger_id=owner&focus_repayment={target}")
        assert focused.status_code == 404

"""Native repayment recovery keeps the original command after an accepted write."""

from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import app.routes._web_debt_write as debt_form_context
import app.services.debt_command_service as commands
from app.database import SessionLocal
from app.errors import AppError
from app.models import Debt, Repayment
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_correction_fx_continuation import _NativeForm
from tests.test_web_debt_actions import _create_debt, _detail


def _repayment_facts(public_id):
    with SessionLocal() as db:
        return list(db.execute(
            select(Repayment.public_id, Repayment.amount_cents, Repayment.paid_at)
            .join(Debt, Debt.id == Repayment.debt_id)
            .where(Debt.public_id == public_id)
        ).all())


@pytest.mark.parametrize("amount_major,amount_minor", [("20.00", 2_000), ("500.00", 50_000)])
def test_native_unknown_result_recovers_same_payment_even_after_settlement(
    web_client, identity, monkeypatch, amount_major, amount_minor,
):
    debt = _create_debt(web_client, identity=identity)
    public_id = debt["public_id"]
    action = f"/web/debts/{public_id}/repayments"
    monkeypatch.setattr(debt_form_context, "accounting_zone", lambda: ZoneInfo("Asia/Shanghai"))
    page = web_client.get(f"/web/debts/{public_id}?ledger_id=owner")
    form = _NativeForm(page.text, action)
    form.set("amount_major", amount_major)
    form.set("paid_at", "2026-09-01")
    original = {name: form.one(name) for name in form.fields}
    response_reader = commands._repayment_response
    fail_once = True

    def read_after_commit(*args, **kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise AppError("dependency_unavailable", "暂时无法读取还款结果。", status_code=503)
        return response_reader(*args, **kwargs)

    monkeypatch.setattr(commands, "_repayment_response", read_after_commit)
    unknown = web_client.post(action, data=original)
    assert unknown.status_code == 503, unknown.text
    accepted = _repayment_facts(public_id)
    assert len(accepted) == 1 and accepted[0].amount_cents == amount_minor

    # Read failure followed commit. Even a now-cleared debt must retain a way to
    # recover that command, rather than offering a replacement at the new OCC.
    forms = hidden_post_forms(unknown.text)
    assert action in forms, "The original repayment needs a reachable recovery form after settlement"
    returned_form = _NativeForm(unknown.text, action)
    recovery = {name: returned_form.one(name) for name in returned_form.fields}
    assert recovery["idempotency_key"] == original["idempotency_key"]
    assert recovery["expected_row_version"] == original["expected_row_version"]
    assert recovery["amount_major"] == amount_major
    assert recovery["paid_at"] == "2026-09-01"

    # A settings change must not reinterpret the saved date during original retry.
    monkeypatch.setattr(debt_form_context, "accounting_zone", lambda: ZoneInfo("America/New_York"))
    retried = web_client.post(action, data=recovery)
    assert retried.status_code == 200, retried.text
    assert _repayment_facts(public_id) == accepted
    assert _detail(web_client, identity=identity, public_id=public_id)["paid_amount_cents"] == amount_minor


def test_missing_occ_retains_native_input_and_original_key(web_client, identity):
    debt = _create_debt(web_client, identity=identity)
    action = f"/web/debts/{debt['public_id']}/repayments"
    page = web_client.get(f"/web/debts/{debt['public_id']}?ledger_id=owner")
    original = hidden_post_forms(page.text)[action]
    refused = web_client.post(action, data={
        **original, "expected_row_version": "", "amount_major": "12.30", "paid_at": "2026-09-02",
    })
    assert refused.status_code in (409, 422), refused.text
    assert "12.30" in refused.text and "2026-09-02" in refused.text
    retained = hidden_post_forms(refused.text)[action]
    assert retained["idempotency_key"] == original["idempotency_key"]
    assert retained["expected_row_version"] == ""
    assert _repayment_facts(debt["public_id"]) == []

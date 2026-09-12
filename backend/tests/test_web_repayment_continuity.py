"""Native repayment recovery keeps the original command after an accepted write."""

import html
import json
import re
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import app.routes._web_debt_write as debt_form_context
import app.routes.web_debt_actions as web_commands
import app.routes.web_debts as web_queries
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
    assert "data-repayment-replacement=" not in unknown.text
    assert "仅作记录，未保存" not in unknown.text
    assert unknown.text.count('id="debt-action-error-repayment"') == 1
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
    returned_form = _NativeForm(refused.text, action)
    retained = {name: returned_form.one(name) for name in returned_form.fields}
    assert retained["amount_major"] == "12.30"
    assert retained["paid_at"] == "2026-09-02"
    assert retained["idempotency_key"] == original["idempotency_key"]
    assert retained["expected_row_version"] == ""
    replacement = re.search(r'data-repayment-replacement="([^"]+)"', refused.text)
    assert replacement is not None
    prepared = json.loads(html.unescape(replacement[1]))
    assert prepared["clientRef"] != original["idempotency_key"]
    assert prepared["values"]["amount_major"] == "12.30"
    assert prepared["values"]["paid_at"] == "2026-09-02"
    assert prepared["values"]["expected_row_version"] == str(debt["row_version"])
    assert _repayment_facts(debt["public_id"]) == []


def test_rejected_overpayment_can_be_corrected_without_losing_its_form(web_client, identity):
    debt = _create_debt(web_client, identity=identity)
    action = f"/web/debts/{debt['public_id']}/repayments"
    form = _NativeForm(web_client.get(f"/web/debts/{debt['public_id']}?ledger_id=owner").text, action)
    form.set("amount_major", "500.01")
    form.set("paid_at", "2026-09-01")
    original = {name: form.one(name) for name in form.fields}
    refused = web_client.post(action, data=original)
    assert refused.status_code == 422, refused.text
    assert 'data-repayment-result="rejected"' in refused.text
    assert _repayment_facts(debt["public_id"]) == []
    returned = _NativeForm(refused.text, action)
    assert returned.one("amount_major") == "500.01"
    returned.set("amount_major", "500.00")
    corrected = web_client.post(action, data={name: returned.one(name) for name in returned.fields})
    assert corrected.status_code == 200, corrected.text
    facts = _repayment_facts(debt["public_id"])
    assert len(facts) == 1 and facts[0].amount_cents == 50_000


def test_exact_acceptance_survives_failure_of_the_following_detail_query(web_client, identity, monkeypatch):
    debt = _create_debt(web_client, identity=identity)
    public_id = debt["public_id"]
    action = f"/web/debts/{public_id}/repayments"
    form = _NativeForm(web_client.get(f"/web/debts/{public_id}?ledger_id=owner").text, action)
    form.set("amount_major", "500.00")
    form.set("paid_at", "2026-09-01")
    original = {name: form.one(name) for name in form.fields}

    def detail_unavailable(*_args, **_kwargs):
        raise AppError("dependency_unavailable", status_code=503)

    monkeypatch.setattr(web_commands, "_render_debt_detail", detail_unavailable)
    accepted = web_client.post(action, data=original)
    assert accepted.status_code == 200, accepted.text
    marker = re.search(r'data-repayment-ack="([^"]+)"', accepted.text)
    assert marker is not None, "A failed subsequent query cannot erase the command acceptance"
    ack = json.loads(html.unescape(marker[1]))
    facts = _repayment_facts(public_id)
    assert len(facts) == 1
    assert ack["repaymentPublicId"] == facts[0].public_id
    assert ack["clientRef"] == original["idempotency_key"]
    assert all(ack["values"][key] == original[key] for key in ack["values"])
    assert "还款事实已记录" in accepted.text


def test_detail_query_failure_keeps_recovery_consumer_without_new_defaults(web_client, identity, monkeypatch):
    debt = _create_debt(web_client, identity=identity)
    public_id = debt["public_id"]

    def detail_unavailable(*_args, **_kwargs):
        raise AppError("dependency_unavailable", status_code=503)

    monkeypatch.setattr(web_queries, "get_participant_debt_response", detail_unavailable)
    unavailable = web_client.get(f"/web/debts/{public_id}?ledger_id=owner")
    assert unavailable.status_code == 503, unavailable.text
    form = _NativeForm(unavailable.text, f"/web/debts/{public_id}/repayments")
    assert 'data-repayment-can-create="false"' in unavailable.text
    assert "/static/web/repayment-entry.js" in unavailable.text
    assert form.one("expected_row_version") == ""
    assert form.one("paid_at") == ""
    assert form.one("amount_major") == ""
    assert form.one("idempotency_key") == ""
    assert _repayment_facts(public_id) == []

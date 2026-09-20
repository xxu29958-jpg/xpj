"""The native agreement task keeps relationship facts and original form intent separate."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.schemas._bill_split_change import BillSplitAgreementResponse, BillSplitChangeProposalResponse
from app.schemas._debts import DebtResponse
from tests._web_debt_test_support import stub_debt


def agreement(**updates):
    stamp = datetime(2026, 9, 20, tzinfo=UTC)
    original = DebtResponse.model_validate({**vars(stub_debt(
        public_id="original", counterparty_type="member", viewer_is_debtor=True,
        source_type="bill_split", source_id="invitation", status="cleared",
        principal_amount_cents=4000, paid_amount_cents=3000, remaining_amount_cents=0,
    )), "ledger_id": "my-ledger", "counterparty_account_id": 2, "created_at": stamp, "updated_at": stamp})
    returned = original.model_copy(update={"public_id": "return", "source_type": "bill_split_return",
        "direction": "owed_to_me", "viewer_is_debtor": False, "status": "open",
        "principal_amount_cents": 1000, "remaining_amount_cents": 1000, "paid_amount_cents": 0})
    values = {"invitation_public_id": "invitation", "home_currency_code": "CNY",
        "original_share_amount_cents": 4000, "agreed_share_amount_cents": 2000,
        "original_debt": original, "return_debt": returned, "viewer_is_party": True,
        "original_paid_amount_cents": 3000, "return_paid_amount_cents": 0,
        "original_forgiven_amount_cents": 0, "return_forgiven_amount_cents": 0,
        "settlement_net_amount_cents": -1000, "preview": {"new_share_amount_cents": 2000,
            "default_settlement_net_amount_cents": -1000, "cash_based_settlement_net_amount_cents": -1000,
            "requires_explicit_settlement": False}}
    return BillSplitAgreementResponse(**{**values, **updates})


def pending_proposal(*, proposed_by_you=False):
    stamp = datetime(2026, 9, 20, tzinfo=UTC)
    return BillSplitChangeProposalResponse(
        public_id="pending-proposal", original_debt_public_id="original", return_debt_public_id="return",
        status="pending", proposed_by_you=proposed_by_you, share_before_amount_cents=4000,
        new_share_amount_cents=2000, settlement_before_net_amount_cents=0,
        settlement_net_amount_cents=-1000, original_paid_amount_cents=3000,
        return_paid_amount_cents=0, original_forgiven_amount_cents=0,
        return_forgiven_amount_cents=0, original_debt_row_version=1, return_debt_row_version=1,
        reason="商家退款后重新分担", created_at=stamp, expires_at=stamp,
    )


def test_cleared_original_does_not_hide_return_obligation_or_rewrite_private_records():
    from app.routes._web_split_agreement import agreement_view, reconcile_member_detail
    from app.routes.web_common import templates

    view = agreement_view(agreement(), selected_id="my-ledger")
    html = templates.get_template("_split_agreement_facts.html").render(agreement=view)
    assert "待返还 ¥10.00" in html
    assert "当前约定份额" in html and "¥20.00" in html
    assert "实际已付款" in html and "¥30.00" in html
    assert "/web/debts/return?ledger_id=my-ledger" in html
    assert "商家退款" in html and "不会自动修改" in html
    debt_view = {"public_id": "original", "is_member": True, "headline": "这件事，我们已经两清啦",
                 "remaining_label": "¥0.00", "member_status_label": "已两清", "member_status_tone": "ok",
                 "show_progress": False}
    reconcile_member_detail(debt_view, view)
    assert debt_view["headline"] == "这件事还有返还待处理"
    assert debt_view["remaining_label"] == "¥10.00"
    assert debt_view["member_status_label"] == "待返还"
    assert debt_view["member_status_tone"] == ""
    assert debt_view["show_progress"] is False

    open_leg_view = {"public_id": "return", "is_member": True, "headline": "我帮你垫的，慢慢来",
                     "remaining_label": "¥10.00", "member_status_label": "进行中"}
    reconcile_member_detail(open_leg_view, view)
    assert open_leg_view["headline"] == "我帮你垫的，慢慢来"

    settled = agreement(return_debt=agreement().return_debt.model_copy(
        update={"status": "cleared", "remaining_amount_cents": 0}), settlement_net_amount_cents=0)
    settled_view = agreement_view(settled, selected_id="my-ledger")
    cleared_view = {"public_id": "original", "is_member": True, "headline": "这件事，我们已经两清啦"}
    reconcile_member_detail(cleared_view, settled_view)
    assert cleared_view["headline"] == "这件事，我们已经两清啦"


def test_default_debt_page_preserves_ledger_records_and_adds_cross_ledger_payables(monkeypatch):
    import app.routes.web_debts as route
    import app.services.debt_service as service

    ledger_rows = [stub_debt(public_id="shared"), stub_debt(public_id="both")]
    monkeypatch.setattr(route, "list_debts", lambda *_a, **_kw: SimpleNamespace(items=ledger_rows))
    def payables(db, *, tenant_id, account_id):
        assert tenant_id == "shared-ledger" and account_id == 4
        return SimpleNamespace(items=[stub_debt(public_id="both"), stub_debt(public_id="cross-return")])
    monkeypatch.setattr(service, "list_payables_for_account", payables)
    rows = route._visible_debts(object(), selected_id="shared-ledger", account_id=4)
    assert [row.public_id for row in rows] == ["shared", "both", "cross-return"]


@pytest.fixture
def native_task(monkeypatch):
    import app.middleware.csrf as csrf
    import app.routes._web_split_change_form as form
    import app.routes.web_split_agreement as route

    request = Request({"type": "http", "method": "GET", "path": "/web/debts/original/split-agreement",
                       "headers": [], "query_string": b"ledger_id=my-ledger"})
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"fixture-csrf-secret")
    scope = {"datasetId": "data", "clientGeneration": "generation", "accountId": "actor",
             "ledgerId": "my-ledger", "deviceId": "device"}
    db = SimpleNamespace(rollback=lambda: None)
    monkeypatch.setattr(form, "repayment_scope", lambda *_: scope)
    monkeypatch.setattr(route, "repayment_scope", lambda *_: scope)
    monkeypatch.setattr(form, "_base_ctx", lambda request, **_: {
        "request": request, "selected_ledger_id": "my-ledger", "selected_ledger_role": "owner",
        "csrf_token": "csrf", "home_currency_code": "CNY", "ledger_options": [],
    })
    monkeypatch.setattr(form, "_debt_write_gate", lambda *_: True)
    monkeypatch.setattr(route, "_list_ledger_options", lambda *_: [])
    monkeypatch.setattr(route, "_resolve_selected_ledger_id", lambda *_a, **_kw: "my-ledger")
    monkeypatch.setattr(route, "_require_selected_ledger_write", lambda *_: None)
    monkeypatch.setattr(route, "require_repayment_binding", lambda *_a, **_kw: None)
    monkeypatch.setattr(route, "resolve_web_actor_account_id", lambda *_: 4)
    monkeypatch.setattr(route, "get_participant_debt_response", lambda *_a, **_kw: agreement().original_debt)
    monkeypatch.setattr(route, "_read", lambda *_a, **_kw: agreement())
    return request, db, form, route


def test_real_template_keeps_immutable_form_and_viewer_read_only(native_task):
    request, db, form, _route = native_task
    response = form.render_change_task(request, db, options=[], selected_id="my-ledger",
                                       public_id="original", agreement=agreement(viewer_is_party=False))
    html = response.body.decode()
    assert 'data-repayment-can-create="false"' in html
    assert "仅由双方本人提出和处理" in html
    assert 'name="expected_return_row_version" value="1"' in html
    assert 'name="origin_binding"' in html
    assert "待返还 ¥10.00" in html
    assert html.count('data-repayment-scope=') == 1


def test_pending_change_blocks_plain_create_but_keeps_replacement_entry(native_task):
    request, db, form, _route = native_task
    facts = agreement(pending_proposal=pending_proposal())
    plain = form.render_change_task(request, db, options=[], selected_id="my-ledger",
                                    public_id="original", agreement=facts)
    plain_html = plain.body.decode()
    assert 'data-repayment-can-create="false"' in plain_html
    assert 'data-split-can-draft="true"' in plain_html
    assert 'href="/web/debts/original/split-agreement?ledger_id=my-ledger&amp;supersedes=pending-proposal"' in plain_html

    replacement = form.render_change_task(request, db, options=[], selected_id="my-ledger",
                                          public_id="original", agreement=facts,
                                          supersedes="pending-proposal")
    assert 'data-repayment-can-create="true"' in replacement.body.decode()


def test_accept_form_can_be_reused_for_explicit_redraft(native_task):
    request, db, form, _route = native_task
    facts = agreement()
    values = form.initial_values(request, db, selected_id="my-ledger", public_id="original", agreement=facts)
    values.update(command="accept", proposal_public_id="old-proposal", reason="原来接受的原因")
    response = form.render_change_task(request, db, options=[], selected_id="my-ledger", public_id="original",
                                       agreement=facts, values=values, result="blocked", rejected=True)
    html = response.body.decode()
    assert '<textarea id="split-reason"' in html
    assert 'id="split-share"' in html
    assert 'data-repayment-preview hidden' in html
    assert 'data-repayment-replacement=' in html
    assert "原来接受的原因" in html
    assert 'required readonly>原来接受的原因</textarea>' in html


def test_accepted_command_ack_survives_agreement_query_failure(native_task, monkeypatch):
    import asyncio
    import html
    import json
    import re

    from app.errors import AppError

    request, db, form, route = native_task
    values = form.initial_values(request, db, selected_id="my-ledger", public_id="original", agreement=agreement())
    values["reason"] = "原商家退款"

    async def retained_form(_request):
        return values

    def execute(*_a, **kwargs):
        assert kwargs["values"] == values
        return SimpleNamespace(public_id="accepted-proposal")

    def unavailable(*_a, **_kw):
        raise AppError("dependency_unavailable", status_code=503)

    monkeypatch.setattr(route, "_form", retained_form)
    monkeypatch.setattr(route, "_execute", execute)
    monkeypatch.setattr(route, "_read", unavailable)
    response = asyncio.run(route._submit(request, db, public_id="original", command="create"))
    assert response.status_code == 200
    rendered = response.body.decode()
    marker = re.search(r'data-repayment-ack="([^"]+)"', rendered)
    ack = json.loads(html.unescape(marker[1]))
    assert ack["clientRef"] == values["idempotency_key"]
    assert ack["values"] == {key: values[key] for key in form.CHANGE_FIELDS}
    assert "这次约定操作已完成" in rendered
    assert "重试读取约定" in rendered


@pytest.mark.parametrize(("error", "status", "replacement"), [
    ("dependency_unavailable", 503, False), ("state_conflict", 409, True),
    ("split_change_repayment_pending", 409, True),
    ("split_total_exceeds_parent", 422, True), ("split_amount_exceeds_parent", 422, True),
])
def test_refusal_or_unknown_result_preserves_original_versions_and_key(native_task, monkeypatch, error, status, replacement):
    import asyncio

    from app.errors import AppError

    request, db, form, route = native_task
    values = form.initial_values(request, db, selected_id="my-ledger", public_id="original", agreement=agreement())
    values.update(reason="保留原原因", expected_row_version="7", expected_return_row_version="3")

    async def retained_form(_request):
        return values

    def fail(*_a, **_kw):
        raise AppError(error, status_code=status)

    monkeypatch.setattr(route, "_form", retained_form)
    monkeypatch.setattr(route, "_execute", fail)
    response = asyncio.run(route._submit(request, db, public_id="original", command="create"))
    rendered = response.body.decode()
    assert response.status_code == status
    assert 'name="expected_row_version" value="7"' in rendered
    assert 'name="expected_return_row_version" value="3"' in rendered
    assert f'name="idempotency_key" value="{values["idempotency_key"]}"' in rendered
    assert "保留原原因" in rendered
    assert ('data-repayment-replacement=' in rendered) == replacement
    assert 'data-repayment-ack=' not in rendered


def test_signed_settlement_and_both_versions_reach_command_payload(native_task):
    request, db, form, route = native_task
    values = form.initial_values(request, db, selected_id="my-ledger", public_id="original", agreement=agreement())
    values.update(reason="双方重新核对", expected_row_version="7", expected_return_row_version="3")
    payload = route._command_payload(values, "CNY")
    assert payload.new_share_amount_cents == 2000
    assert payload.settlement_net_amount_cents == -1000
    assert payload.expected_row_version == 7 and payload.expected_return_row_version == 3


def test_mismatched_command_is_retained_without_error_page_crash(native_task, monkeypatch):
    import asyncio

    request, db, form, route = native_task
    values = form.initial_values(request, db, selected_id="my-ledger", public_id="original", agreement=agreement())
    values.update(command="unknown-command", home_currency_code="unknown-currency")

    async def retained_form(_request):
        return values

    monkeypatch.setattr(route, "_form", retained_form)
    response = asyncio.run(route._submit(request, db, public_id="original", command="create"))
    assert response.status_code == 409
    assert 'name="command" value="unknown-command"' in response.body.decode()


@pytest.mark.parametrize("scenario", ["preview", "command_replacement", "ack_and_repayment"])
def test_split_original_browser_submission(scenario):
    import shutil
    import subprocess
    from pathlib import Path

    root = Path(__file__).parents[1]
    result = subprocess.run(
        [shutil.which("node"), str(root / "tests/fixtures/split_change_draft_contract.cjs"),
         str(root / "app/static/web/manual-drafts.js"), str(root / "app/static/web/repayment-entry.js"), scenario],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr

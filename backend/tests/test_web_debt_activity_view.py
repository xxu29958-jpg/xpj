"""The participant history renders retained facts without another balance fold."""

from datetime import UTC, datetime

import pytest

from app.routes.web_common import templates
from app.schemas._debt_activity import DebtActivityListResponse, DebtActivityResponse
from app.schemas._debts import MemberRepaymentProposalResponse, RepaymentFactResponse


def _page(items, *, page=2, total=42):
    return DebtActivityListResponse(
        debt_public_id="debt-one", home_currency_code="CNY", items=items,
        page=page, page_size=20, total=total,
    )


def _repayment():
    return RepaymentFactResponse(
        public_id="repay-one", amount_cents=4000, original_currency_code="USD",
        original_amount_minor=550, exchange_rate_to_cny="7.27272727",
        exchange_rate_date="2026-09-10", exchange_rate_source="manual",
        paid_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
        created_at=datetime(2026, 9, 11, 12, tzinfo=UTC), status="active",
    )


def test_partial_proposal_shows_actual_confirmation_and_reachable_fact():
    from app.routes._web_debt_activity import activity_view

    proposal = MemberRepaymentProposalResponse(
        public_id="proposal-one", debt_public_id="debt-one", status="partially_confirmed",
        proposed_amount_cents=10000, confirmed_amount_cents=4000, home_currency_code="CNY",
        paid_at=datetime(2026, 9, 10, tzinfo=UTC), created_at=datetime(2026, 9, 11, tzinfo=UTC),
        expires_at=datetime(2026, 10, 11, tzinfo=UTC), resolved_at=datetime(2026, 9, 12, tzinfo=UTC),
        committed_repayment_public_id="repay-one", note="先确认收到的一部分",
    )
    event = DebtActivityResponse(
        kind="proposal_resolved", public_id=proposal.public_id,
        recorded_at=proposal.resolved_at, actor_is_you=False, actor_display_name="家人",
        proposal=proposal,
    )
    view = activity_view(_page([event]), selected_id="my-ledger")
    row = view["rows"][0]
    assert row["proposal"]["amount_label"] == "¥100.00"
    assert row["proposal"]["confirmed_amount_label"] == "¥40.00"
    assert "focus_repayment=repay-one" in row["repayment_href"]
    assert row["repayment_href"].endswith("#repayment-repay-one")
    assert "ledger_id=my-ledger" in row["repayment_href"]
    html = templates.get_template("_debt_activity.html").render(
        activity=view, debt={"is_member": True, "public_id": "debt-one"}, can_write=False,
        action_form={"kind": ""}, selected_ledger_id="my-ledger",
    )
    assert "申报 ¥100.00" in html and "实际确认 ¥40.00" in html
    assert "申报本身不计入已偿还金额" in html
    assert "先确认收到的一部分" in html
    assert "activity_page=3" in html and "activity_page=1" in html
    assert "调整金额" not in html


def test_repayment_retains_frozen_fx_paid_date_and_void_intent_on_older_page():
    from app.routes._web_debt_activity import activity_view

    event = DebtActivityResponse(
        kind="repayment", public_id="repay-one", recorded_at=_repayment().created_at,
        actor_is_you=True, repayment=_repayment(),
    )
    view = activity_view(_page([event]), selected_id="my-ledger")
    html = templates.get_template("_debt_activity.html").render(
        activity=view, debt={"is_member": False, "public_id": "debt-one"}, can_write=True,
        action_form={"kind": "repayment_void", "target_public_id": "repay-one",
                     "draft": {"reason": "填错了", "idempotency_key": "original-key"}, "error": "请核对"},
        selected_ledger_id="my-ledger", csrf_token="csrf", expected_row_version=7,
    )
    assert 'id="repayment-repay-one"' in html
    assert "付款日期 2026-09-10" in html and "记录于 2026-09-11" in html
    assert "$5.50" in html and "7.27272727" in html and "手动汇率" in html
    assert " · manual" not in html
    assert 'action="/web/debts/debt-one/repayment-voids?activity_page=2"' in html
    assert 'name="idempotency_key" value="original-key"' in html
    assert 'name="expected_row_version" value="7"' in html
    assert 'name="csrf_token" value="csrf"' in html
    assert 'value="填错了"' in html


def test_mixed_facts_keep_signed_adjustment_and_do_not_invent_void_amount():
    from app.routes._web_debt_activity import activity_view

    items = [DebtActivityResponse(
        kind=kind, public_id=kind, recorded_at=datetime(2026, 9, 12, tzinfo=UTC),
        actor_is_you=False, actor_display_name="家人", amount_cents=amount, reason="保留原因",
    ) for kind, amount in [("created", 10000), ("adjustment", -3000), ("forgiveness", 2000), ("debt_void", None)]]
    rows = activity_view(_page(items), selected_id="my-ledger")["rows"]
    assert [row["title"] for row in rows] == ["建立往来", "调整金额", "免除余额", "作废整笔往来"]
    assert rows[1]["amount_label"] == "-¥30.00"
    assert rows[3]["amount_label"] == ""
    assert all(row["reason"] == "保留原因" and row["actor_label"] == "家人" for row in rows)


def representative_response(monkeypatch):
    """Render the actual detail route with fictional read-owner results, without IO."""
    from starlette.requests import Request

    import app.middleware.csrf as csrf
    import app.routes._web_debt_repayment as repayment
    import app.routes.web_debts as route
    import app.services.debt_service as service
    from app.schemas._debts import RepaymentVoidFactResponse
    from tests._web_debt_test_support import stub_debt

    timestamp = datetime(2026, 9, 12, 12, tzinfo=UTC)
    proposal = MemberRepaymentProposalResponse(
        public_id="proposal-one", debt_public_id="debt-one", status="partially_confirmed",
        proposed_amount_cents=10000, confirmed_amount_cents=4000, home_currency_code="CNY",
        paid_at=timestamp, created_at=timestamp, expires_at=timestamp, resolved_at=timestamp,
        committed_repayment_public_id="repay-one", note="先确认收到的一部分",
    )
    fact = _repayment().model_copy(update={"status": "voided", "void_fact": RepaymentVoidFactResponse(
        public_id="void-one", reason="误记了同一笔转账", created_at=timestamp,
    )})
    items = [
        DebtActivityResponse(kind="proposal_resolved", public_id=proposal.public_id,
                             recorded_at=timestamp, actor_is_you=True, proposal=proposal),
        DebtActivityResponse(kind="repayment_void", public_id="void-one", recorded_at=timestamp,
                             actor_is_you=True, reason="误记了同一笔转账", repayment=fact),
        DebtActivityResponse(kind="repayment", public_id=fact.public_id, recorded_at=fact.created_at,
                             actor_is_you=False, actor_display_name="家人", repayment=fact),
    ]
    listing = _page(items)
    debt = stub_debt(public_id="debt-one", counterparty_type="member", counterparty_label="一起出行的家人",
                     viewer_is_debtor=False, paid_amount_cents=4000, remaining_amount_cents=46000)
    request = Request({"type": "http", "method": "GET", "scheme": "http", "server": ("testserver", 80),
                       "path": "/web/debts/debt-one", "query_string": b"ledger_id=my-ledger&activity_page=2",
                       "headers": []})
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"fictional-render-test-secret")
    context = {
        "request": request, "debt": route._detail_view(debt), "can_write": False,
        "debt_open": True, "action_keys": {}, "proposals": None, "pending_proposal": None,
        "viewer_is_debtor": False, "currency_input": route._currency_input_view("CNY"),
        "expected_row_version": 7, "selected_ledger_id": "my-ledger", "ledger_options": [],
        "home_currency_code": "CNY", "home_currency_symbol": "¥", "home_currency_minor_digits": 2,
        "asset_version": "relationship-preview", "sidebar_counts": {}, "csrf_token": "example",
    }
    monkeypatch.setattr(route, "_load_debt_detail_state", lambda *_a, **_kw: (context, debt, 3, []))
    monkeypatch.setattr(repayment, "repayment_context", lambda *_a, **_kw: {})
    calls = []
    def list_activity(db, **kwargs):
        calls.append(kwargs)
        return listing
    monkeypatch.setattr(service, "list_debt_activity", list_activity)
    response = route._render_debt_detail(request, object(), options=[], selected_id="my-ledger", public_id="debt-one")
    return response, calls


def test_actual_detail_renderer_reads_requested_page_and_has_one_history(monkeypatch):
    response, calls = representative_response(monkeypatch)
    html = response.body.decode()
    assert response.status_code == 200
    assert calls == [{"tenant_id": "my-ledger", "actor_account_id": 3, "public_id": "debt-one",
                      "page": 2, "page_size": 20, "focus_repayment": None}]
    assert html.count('id="debt-facts-title"') == 1
    assert "申报 ¥100.00 · 实际确认 ¥40.00" in html
    assert "误记了同一笔转账" in html
    assert "activity_page=3" in html and "activity_page=1" in html
    assert "debt-history-more" not in html
    assert "/repayment-voids" not in html


def test_already_voided_fact_keeps_failed_attempt_visible_without_another_submit():
    from app.routes._web_debt_activity import activity_view
    from app.schemas._debts import RepaymentVoidFactResponse

    fact = _repayment().model_copy(update={"status": "voided", "void_fact": RepaymentVoidFactResponse(
        public_id="void-one", reason="先到的更正", created_at=datetime(2026, 9, 12, tzinfo=UTC),
    )})
    event = DebtActivityResponse(kind="repayment", public_id=fact.public_id,
                                 recorded_at=fact.created_at, actor_is_you=True, repayment=fact)
    html = templates.get_template("_debt_activity.html").render(
        activity=activity_view(_page([event]), selected_id="my-ledger"),
        debt={"is_member": False, "public_id": "debt-one"}, can_write=True,
        action_form={"kind": "repayment_void", "target_public_id": "repay-one", "fallback": False,
                     "error": "另一端已经撤销", "draft": {"reason": "我填写的原因"}},
    )
    assert 'id="debt-action-error-repayment_void-repay-one"' in html
    assert "我填写的原因" in html and "先到的更正" in html
    assert "/repayment-voids" not in html


@pytest.mark.parametrize("debt_status, can_void", [("open", True), ("cleared", True), ("voided", False)])
def test_repayment_void_action_respects_whole_debt_terminal_state(debt_status, can_void):
    from app.routes._web_debt_activity import activity_view
    from app.routes.web_debts import _detail_view
    from tests._web_debt_test_support import stub_debt

    fact = _repayment()
    event = DebtActivityResponse(kind="repayment", public_id=fact.public_id,
                                 recorded_at=fact.created_at, actor_is_you=True, repayment=fact)
    debt = stub_debt(public_id="debt-one", status=debt_status,
                     remaining_amount_cents=4000 if debt_status == "open" else 0)
    html = templates.get_template("_debt_activity.html").render(
        activity=activity_view(_page([event]), selected_id="my-ledger"),
        debt=_detail_view(debt), debt_open=debt_status == "open", can_write=True,
        action_form={"kind": ""}, selected_ledger_id="my-ledger",
        csrf_token="csrf", expected_row_version=7,
    )
    assert ('action="/web/debts/debt-one/repayment-voids' in html) is can_void
    assert 'id="repayment-repay-one"' in html
    assert "付款日期 2026-09-10" in html and "$5.50" in html

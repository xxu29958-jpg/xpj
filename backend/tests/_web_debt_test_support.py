"""Pure fixture builders shared by the Web debt projection tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.schemas._debt_activity import DebtActivityListResponse, DebtActivityResponse
from app.schemas._debts import MemberRepaymentProposalResponse, RepaymentFactResponse


def stub_debt(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "public_id": "dbt_1",
        "counterparty_label": "招商信用卡",
        "note": None,
        "counterparty_type": "external",
        "direction": "i_owe",
        "status": "open",
        "remaining_amount_cents": 50000,
        "principal_amount_cents": 50000,
        "paid_amount_cents": 0,
        "home_currency_code": "CNY",
        "original_currency_code": None,
        "viewer_is_debtor": None,
        "is_forgiven": False,
        "row_version": 1,
        "repayment_calendar": None,
        "source_type": "manual",
        # Non-installment defaults keep the schedule card absent unless a test
        # explicitly supplies the installment contract.
        "debt_kind": "unspecified",
        "installment_count": None,
        "installment_period_months": None,
        "installment_paid_count": None,
        "installment_payoff_date": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


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


def representative_response(monkeypatch):
    """Render the actual detail route with fictional read-owner results, without IO."""
    from starlette.requests import Request

    import app.middleware.csrf as csrf
    import app.routes.web_debts as route
    import app.services.debt_service as service
    from app.schemas._debts import RepaymentVoidFactResponse

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
    debt = stub_debt(public_id="debt-one", ledger_id="my-ledger", counterparty_type="member", counterparty_label="一起出行的家人",
                     viewer_is_debtor=False, paid_amount_cents=4000, remaining_amount_cents=46000)
    request = Request({"type": "http", "method": "GET", "scheme": "http", "server": ("testserver", 80),
                       "path": "/web/debts/debt-one", "query_string": b"ledger_id=my-ledger&activity_page=2",
                       "headers": []})
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"fictional-render-test-secret")
    context = {
        "request": request, "debt": route._detail_view(debt), "can_write": False, "can_change_member_kind": False,
        "debt_open": True, "action_keys": {}, "proposals": None, "pending_proposal": None,
        "viewer_is_debtor": False, "currency_input": route._currency_input_view("CNY"),
        "expected_row_version": 7, "selected_ledger_id": "my-ledger", "ledger_options": [],
        "home_currency_code": "CNY", "home_currency_symbol": "¥", "home_currency_minor_digits": 2,
        "asset_version": "relationship-preview", "sidebar_counts": {}, "csrf_token": "example",
    }
    monkeypatch.setattr(route, "_load_debt_detail_state", lambda *_a, **_kw: (context, debt, 3, []))
    calls = []
    def list_activity(db, **kwargs):
        calls.append(kwargs)
        return listing
    monkeypatch.setattr(service, "list_debt_activity", list_activity)
    response = route._render_debt_detail(request, object(), options=[], selected_id="my-ledger", public_id="debt-one")
    return response, calls

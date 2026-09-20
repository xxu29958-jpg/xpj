"""Web projection of participant-visible history; balances stay with Debt."""

from urllib.parse import urlencode
from uuid import uuid4

from app.errors import AppError
from app.routes._web_debt_write import _day_label, _resolved_proposal_row
from app.routes._web_money_views import _exchange_rate_source_label
from app.routes.web_common import _home_amount_label
from app.schemas._debt_activity import DebtActivityListResponse, DebtActivityResponse
from app.services.currency_common import minor_amount_label
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import ensure_utc

_TITLES = {
    "created": "建立往来", "repayment": "还款到账", "repayment_void": "撤销还款",
    "adjustment": "调整金额", "forgiveness": "免除余额", "debt_void": "作废整笔往来",
    "proposal_created": "申报还款", "proposal_resolved": "处理还款申报",
    "split_change_proposed": "提出新约定", "split_change_resolved": "处理约定提议",
    "split_agreement_changed": "双方接受新约定",
}


def _activity_href(public_id: str, selected_id: str, **query) -> str:
    return f"/web/debts/{public_id}?{urlencode({'ledger_id': selected_id, **query})}"


def _repayment_view(fact, home: str) -> dict:
    void = fact.void_fact
    return {
        "public_id": fact.public_id,
        "amount_label": _home_amount_label(fact.amount_cents, home),
        "date_text": _day_label(fact.paid_at),
        "original_label": (
            minor_amount_label(fact.original_amount_minor, fact.original_currency_code)
            if fact.original_currency_code and fact.original_amount_minor is not None else ""
        ),
        "exchange_rate": fact.exchange_rate_to_cny,
        "exchange_rate_date": ensure_utc(fact.exchange_rate_date).date().isoformat() if fact.exchange_rate_date else "",
        "exchange_rate_source": _exchange_rate_source_label(fact.exchange_rate_source) if fact.exchange_rate_source else "",
        "is_voided": fact.status == "voided",
        "void_reason": void.reason if void else "",
        "void_date_text": _day_label(void.created_at) if void else "",
        "void_key": str(uuid4()),
    }


def _proposal_view(event: DebtActivityResponse) -> dict:
    proposal = event.proposal
    if proposal is None:
        return {}
    view = _resolved_proposal_row(proposal)
    view.update({
        "paid_at": _day_label(proposal.paid_at),
        "confirmed_amount_label": (
            _home_amount_label(proposal.confirmed_amount_cents, proposal.home_currency_code)
            if event.kind == "proposal_resolved" and proposal.confirmed_amount_cents is not None else ""
        ),
        "original_label": (
            minor_amount_label(proposal.original_amount_minor, proposal.original_currency_code)
            if proposal.original_currency_code and proposal.original_amount_minor is not None else ""
        ),
    })
    return view


def _split_view(event: DebtActivityResponse, home: str) -> dict:
    proposal = event.split_change
    if proposal is None:
        return {}
    net = proposal.settlement_net_amount_cents
    settlement = ("受邀方待付 " if net > 0 else "发起方待返还 ") + _home_amount_label(abs(net), home)
    return {
        "share_label": f"{_home_amount_label(proposal.share_before_amount_cents, home)} → "
                       f"{_home_amount_label(proposal.new_share_amount_cents, home)}",
        "settlement_label": settlement if net else "双方暂无待结算",
        "original_paid_label": _home_amount_label(proposal.original_paid_amount_cents, home),
        "return_paid_label": _home_amount_label(proposal.return_paid_amount_cents, home),
        "original_forgiven_label": _home_amount_label(proposal.original_forgiven_amount_cents, home),
        "return_forgiven_label": _home_amount_label(proposal.return_forgiven_amount_cents, home),
        "status_label": {"pending": "待对方确认", "accepted": "已接受", "rejected": "已拒绝",
                         "withdrawn": "已撤回", "superseded": "已被新提议替代", "expired": "已过期"}[proposal.status],
    }


def _activity_row(event: DebtActivityResponse, listing: DebtActivityListResponse, selected_id: str) -> dict:
    repayment = event.repayment
    proposal = event.proposal
    linked_repayment = proposal.committed_repayment_public_id if proposal and event.kind == "proposal_resolved" else None
    if event.kind == "repayment_void" and repayment:
        linked_repayment = repayment.public_id
    return {
        "kind": event.kind,
        "public_id": event.public_id,
        "anchor": f"{event.kind}-{event.public_id}",
        "title": _TITLES[event.kind],
        "recorded_at": ensure_utc(event.recorded_at).astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M"),
        "actor_label": "你" if event.actor_is_you else (event.actor_display_name or "未记录操作者"),
        "amount_label": _home_amount_label(event.amount_cents, listing.home_currency_code) if event.amount_cents is not None else "",
        "reason": event.reason or "",
        "repayment": _repayment_view(repayment, listing.home_currency_code) if repayment else None,
        "proposal": _proposal_view(event),
        "split_change": _split_view(event, listing.home_currency_code),
        "repayment_href": (
            _activity_href(listing.debt_public_id, selected_id, focus_repayment=linked_repayment)
            + f"#repayment-{linked_repayment}" if linked_repayment else ""
        ),
    }


def activity_view(listing: DebtActivityListResponse, *, selected_id: str) -> dict:
    return {
        "rows": [_activity_row(event, listing, selected_id) for event in listing.items],
        "page": listing.page,
        "total": listing.total,
        "previous_href": (
            _activity_href(listing.debt_public_id, selected_id, activity_page=listing.page - 1) + "#debt-activity"
            if listing.page > 1 else ""
        ),
        "next_href": (
            _activity_href(listing.debt_public_id, selected_id, activity_page=listing.page + 1) + "#debt-activity"
            if listing.page * listing.page_size < listing.total else ""
        ),
    }


def debt_activity_context(
    request, db, *, selected_id: str, account_id: int | None, public_id: str,
    focus_repayment: str | None = None,
) -> dict:
    from app.services.debt_service import list_debt_activity

    try:
        page = int(request.query_params.get("activity_page", "1"))
    except ValueError as exc:
        raise AppError("invalid_request", "请选择正确的历史页码。", status_code=422) from exc
    if page < 1:
        raise AppError("invalid_request", "请选择正确的历史页码。", status_code=422)
    if account_id is None:
        return {"rows": [], "page": page, "total": 0, "previous_href": "", "next_href": ""}
    query = {
        "tenant_id": selected_id, "actor_account_id": account_id, "public_id": public_id,
        "page": page, "page_size": 20,
    }
    try:
        listing = list_debt_activity(
            db, **query, focus_repayment=focus_repayment or request.query_params.get("focus_repayment"),
        )
    except AppError as exc:
        if focus_repayment is None or exc.error != "repayment_not_found":
            raise
        # A rejected command may name a missing/foreign repayment. Keep the
        # debt page available for its feedback; direct GET focus stays strict.
        listing = list_debt_activity(db, **query)
    return activity_view(listing, selected_id=selected_id)

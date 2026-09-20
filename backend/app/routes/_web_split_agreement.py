"""Participant-safe projection of the shared split agreement read owner."""

from urllib.parse import urlencode

from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError
from app.routes.web_common import _home_amount_label
from app.services import bill_split_service


def agreement_href(public_id: str, selected_id: str) -> str:
    return f"/web/debts/{public_id}/split-agreement?{urlencode({'ledger_id': selected_id})}"


def settlement_label(amount: int, currency: str) -> str:
    if amount == 0:
        return "两边暂无待结算"
    direction = "待付款" if amount > 0 else "待返还"
    return f"{direction} {_home_amount_label(abs(amount), currency)}"


def agreement_view(agreement, *, selected_id: str) -> dict:
    currency = agreement.home_currency_code
    result = {"facts": agreement, "href": agreement_href(agreement.original_debt.public_id, selected_id),
              "settlement_label": settlement_label(agreement.settlement_net_amount_cents, currency)}
    for field in ("original_share", "agreed_share", "original_paid", "return_paid", "original_forgiven", "return_forgiven"):
        result[field + "_label"] = _home_amount_label(getattr(agreement, field + "_amount_cents"), currency)
    result["legs"] = [{"label": label, "remaining_label": _home_amount_label(debt.remaining_amount_cents, currency),
                       "href": f"/web/debts/{debt.public_id}?{urlencode({'ledger_id': selected_id})}"}
                      for label, debt in (("原付款往来", agreement.original_debt), ("返还往来", agreement.return_debt))
                      if debt is not None]
    result["preview_label"] = settlement_label(agreement.preview.default_settlement_net_amount_cents, currency)
    reference = agreement.preview.cash_based_settlement_net_amount_cents
    result["reference_label"] = settlement_label(reference, currency) if reference is not None else ""
    result["pending_repayments"] = [{"href": f"/web/debts/{public_id}?{urlencode({'ledger_id': selected_id})}#debt-proposal-actions-title",
                                     "label": "核对原付款" if public_id == agreement.original_debt.public_id else "核对返还付款"}
                                    for public_id in agreement.pending_repayment_debt_public_ids]
    open_legs = [debt for debt in (agreement.original_debt, agreement.return_debt)
                 if debt is not None and debt.status == "open"]
    if open_legs and agreement.settlement_net_amount_cents:
        returning = agreement.settlement_net_amount_cents < 0
        direction = "返还" if returning else "付款"
        result["member_relationship"] = {
            "headline": f"这件事还有{direction}待处理",
            "remaining_label": _home_amount_label(abs(agreement.settlement_net_amount_cents), currency),
            "member_status_label": f"待{direction}",
            "member_status_tone": "",
            "show_progress": False,
        }
    return result


def reconcile_member_detail(debt_view: dict, agreement: dict | None) -> None:
    """Keep a cleared split leg from declaring the whole two-leg relationship settled."""
    if not debt_view.get("is_member") or not agreement or agreement.get("error"):
        return
    relationship = agreement.get("member_relationship")
    facts = agreement.get("facts")
    if not relationship or facts is None:
        return
    legs = [debt for debt in (facts.original_debt, facts.return_debt) if debt is not None]
    current = next((debt for debt in legs if debt.public_id == debt_view.get("public_id")), None)
    if current is not None and current.status == "cleared" and any(debt.status == "open" for debt in legs):
        debt_view.update(relationship)


def split_agreement_context(request, db, *, debt, selected_id: str, account_id: int | None) -> dict | None:
    if debt.source_type not in {"bill_split", "bill_split_return"}:
        return None
    href = agreement_href(debt.public_id, selected_id)
    if account_id is None:
        return {"href": href, "error": "请使用原参与账户查看拆账约定。"}
    try:
        agreement = bill_split_service.get_bill_split_agreement(
            db, tenant_id=selected_id, actor_account_id=account_id, public_id=debt.public_id,
        )
    except (AppError, SQLAlchemyError):
        db.rollback()
        return {"href": href, "error": "拆账约定暂时无法读取；原往来与已有操作仍可使用。"}
    return agreement_view(agreement, selected_id=selected_id)

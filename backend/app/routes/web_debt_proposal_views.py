"""Presentation helpers for member repayment proposals on Web Debt detail."""

from __future__ import annotations

from app.routes.web_common import _home_amount_label, _minor_amount_value
from app.services.spending_contract_service import accounting_zone

_PROPOSAL_STATUS_LABELS = {
    "pending": "待 TA 确认",
    "confirmed": "已两清",
    "partially_confirmed": "收了一部分",
    "rejected": "在对账",
    "withdrawn": "已撤回",
    "expired": "这次没对上",
    "superseded": "重记过了",
}
_PROPOSAL_HISTORY_TITLE = "过往"
_PROPOSAL_HISTORY_COLLAPSED = 3
_PROPOSAL_DATE_CONFIRMED = "{} 对上"
_PROPOSAL_DATE_PARTIAL = "{} 收了一部分"


def _day_label(value) -> str:
    """Render proposal dates at accounting-day precision."""
    if value is None:
        return ""
    return value.astimezone(accounting_zone()).strftime("%Y-%m-%d")


def _proposal_pending_line(pending, viewer_is_debtor: bool | None) -> str:
    """Describe who owns the next step without turning the relation into a score."""
    if viewer_is_debtor is True:
        return "你说你还了这一份，等家人确认一下"
    if viewer_is_debtor is False:
        amount = _home_amount_label(
            pending.proposed_amount_cents,
            pending.home_currency_code,
        )
        return f"TA 把 {amount} 那份给你啦，看看对不对"
    return "他们之间有一笔正在确认"


def _resolved_proposal_row(proposal) -> dict:
    """Project a resolved proposal into a neutral, auditable history row."""
    day = _day_label(proposal.resolved_at or proposal.created_at)
    if proposal.status == "confirmed":
        date_text = _PROPOSAL_DATE_CONFIRMED.format(day)
    elif proposal.status == "partially_confirmed":
        date_text = _PROPOSAL_DATE_PARTIAL.format(day)
    else:
        date_text = day
    return {
        "amount_label": _home_amount_label(
            proposal.proposed_amount_cents,
            proposal.home_currency_code,
        ),
        "note": (proposal.note or "").strip() or None,
        "date_text": date_text,
        "status_label": _PROPOSAL_STATUS_LABELS.get(
            proposal.status,
            _PROPOSAL_STATUS_LABELS["pending"],
        ),
    }


def _proposal_section(
    proposals,
    viewer_is_debtor: bool | None,
    *,
    debt_status: str,
) -> dict:
    """Build the role-aware proposal inbox and resolved history projection."""
    pending = next((p for p in proposals if p.status == "pending"), None)
    resolved_rows = [_resolved_proposal_row(p) for p in proposals if p.status != "pending"]
    latest_resolved = next((p for p in proposals if p.status != "pending"), None)
    is_open = debt_status == "open"
    return {
        "pending_line": (_proposal_pending_line(pending, viewer_is_debtor) if pending else None),
        "pending": (
            {
                "public_id": pending.public_id,
                "amount_label": _home_amount_label(
                    pending.proposed_amount_cents,
                    pending.home_currency_code,
                ),
                "amount_value": _minor_amount_value(
                    pending.proposed_amount_cents,
                    pending.home_currency_code,
                ),
                "note": (pending.note or "").strip() or None,
            }
            if pending
            else None
        ),
        "can_propose": is_open and viewer_is_debtor is True and pending is None,
        "can_withdraw": is_open and viewer_is_debtor is True and pending is not None,
        "can_confirm": is_open and viewer_is_debtor is False and pending is not None,
        "can_reject": is_open and viewer_is_debtor is False and pending is not None,
        "show_debtor_after_reject": (
            is_open
            and viewer_is_debtor is True
            and pending is None
            and latest_resolved is not None
            and latest_resolved.status == "rejected"
        ),
        "is_creditor_waiting": (is_open and viewer_is_debtor is False and pending is None),
        "is_not_party": viewer_is_debtor is None,
        "history_title": _PROPOSAL_HISTORY_TITLE,
        "resolved_visible": resolved_rows[:_PROPOSAL_HISTORY_COLLAPSED],
        "resolved_hidden": resolved_rows[_PROPOSAL_HISTORY_COLLAPSED:],
        "history_expand_label": f"查看全部 {len(resolved_rows)} 条过往",
        "has_resolved": bool(resolved_rows),
    }

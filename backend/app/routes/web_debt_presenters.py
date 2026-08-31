"""Pure view builders shared by the Web debt list and detail routes."""

from __future__ import annotations

from app.routes.web_common import _home_amount_label

_MEMBER_NEAR_RATIO = 0.7
_MEMBER_SOME_RATIO = 0.5
_MEMBER_HEADLINES = {
    "i_owe_start": "你帮我垫了，慢慢还给你",
    "i_owe_early": "你帮我垫的，正在慢慢对上",
    "i_owe_near": "你帮我垫的，快两清啦",
    "owed_start": "我帮你垫的，不着急",
    "owed_early": "我帮你垫的，慢慢来",
    "owed_near": "我帮你垫的，快两清啦",
    "cleared": "这件事，我们已经两清啦",
    "forgiven_debtor": "这份 TA 说不用还啦 ❤️",
    "forgiven_creditor": "这份不用补了～",
    "voided": "这件事已经不算了",
    "third_party_progress": "这件事还在进行中",
    "third_party_cleared": "这件事，他们已经两清啦",
}
_MEMBER_PROGRESS_NOTE = {
    "none": "还没开始对账",
    "some": "已经对上一部分",
    "most": "这件事已对上大半",
}


def _communal_ratio(paid_cents: int, principal_cents: int) -> float:
    if principal_cents <= 0:
        return 0.0
    return max(0.0, min(1.0, paid_cents / principal_cents))


def _member_headline(
    viewer_is_debtor: bool | None,
    status: str,
    is_forgiven: bool,
    ratio: float,
) -> str:
    if viewer_is_debtor is None:
        if status == "cleared":
            return _MEMBER_HEADLINES["third_party_cleared"]
        if status == "voided":
            return _MEMBER_HEADLINES["voided"]
        return _MEMBER_HEADLINES["third_party_progress"]
    if status == "voided":
        return _MEMBER_HEADLINES["voided"]
    if status == "cleared":
        if is_forgiven and viewer_is_debtor:
            return _MEMBER_HEADLINES["forgiven_debtor"]
        if is_forgiven:
            return _MEMBER_HEADLINES["forgiven_creditor"]
        return _MEMBER_HEADLINES["cleared"]
    if ratio <= 0:
        return _MEMBER_HEADLINES["i_owe_start" if viewer_is_debtor else "owed_start"]
    if ratio < _MEMBER_NEAR_RATIO:
        return _MEMBER_HEADLINES["i_owe_early" if viewer_is_debtor else "owed_early"]
    return _MEMBER_HEADLINES["i_owe_near" if viewer_is_debtor else "owed_near"]


def _member_progress_note(ratio: float) -> str:
    if ratio <= 0:
        return _MEMBER_PROGRESS_NOTE["none"]
    if ratio <= _MEMBER_SOME_RATIO:
        return _MEMBER_PROGRESS_NOTE["some"]
    return _MEMBER_PROGRESS_NOTE["most"]


def _installment_view(debt, home: str) -> dict | None:
    count = debt.installment_count
    if debt.debt_kind != "installment" or count is None or debt.status != "open":
        return None
    period = debt.installment_period_months
    schedule = (
        f"共 {count} 期 · 每月一期"
        if period in (None, 1)
        else f"共 {count} 期 · 每 {period} 个月一期"
    )
    paid = min(debt.installment_paid_count or 0, count)
    payoff = debt.installment_payoff_date
    per_period_cents = debt.principal_amount_cents // count
    return {
        "schedule_label": schedule,
        "progress_label": f"已还 {paid} / {count} 期",
        "payoff_label": (
            f"按分期合约，预计 {payoff.year} 年 {payoff.month} 月还清"
            if payoff is not None
            else None
        ),
        "per_period_label": (
            f"每期约 {_home_amount_label(per_period_cents, home)} · 估算不含手续费"
        ),
    }


def _proposal_feedback_context(
    proposal_items,
    *,
    confirm_amount_error: str | None,
    confirm_amount_value: str | None,
    confirm_error_proposal_id: str | None,
    currency_symbol: str,
    status_code: int,
) -> dict:
    submitted = next(
        (item for item in proposal_items if item.public_id == confirm_error_proposal_id),
        None,
    )
    return {
        "confirm_amount_error": confirm_amount_error,
        "confirm_amount_value": confirm_amount_value,
        "confirm_error_proposal_id": confirm_error_proposal_id,
        "confirm_amount_attempted_label": (
            f"{currency_symbol}{confirm_amount_value}"
            if status_code == 409 and confirm_amount_value
            else ""
        ),
        "confirm_error_proposal_amount_label": (
            _home_amount_label(
                submitted.proposed_amount_cents,
                submitted.home_currency_code,
            )
            if submitted is not None
            else ""
        ),
    }


def _action_feedback_context(
    *,
    action_keys: dict,
    can_write: bool,
    debt_status: str,
    action_kind: str | None,
    action_error: str | None,
    action_draft: dict[str, str] | None,
    action_target_public_id: str | None,
    action_conflict: bool,
    currency_symbol: str,
    flash_message: str,
    flash_type: str,
) -> dict:
    fallback = bool(action_error and not (can_write and debt_status == "open" and action_keys))
    message = action_error or ""
    if fallback and action_conflict:
        message = (
            "这笔欠款刚在另一端结束了，你刚才填写的还款没有记录。"
            if action_kind == "repayment"
            else "这笔欠款刚在另一端结束了，你刚才的操作没有记录。"
        )
    draft = action_draft or {}
    attempted_parts: list[str] = []
    if fallback and action_kind == "repayment":
        amount = (draft.get("amount_major") or "").strip()
        paid_at = (draft.get("paid_at") or "").strip()
        if amount:
            attempted_parts.append(f"本次还款 {currency_symbol}{amount}")
        if paid_at:
            attempted_parts.append(paid_at)
    return {
        "action_form": {
            "kind": action_kind or "",
            "error": message,
            "draft": draft,
            "target_public_id": action_target_public_id or "",
            "fallback": fallback,
            "attempted_label": " · ".join(attempted_parts),
        },
        "flash_message": flash_message,
        "flash_type": flash_type if flash_type in ("success", "error") else "",
    }

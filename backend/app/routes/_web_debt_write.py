"""Write-surface context helpers for the /web/debts pages (slice C2).

Native to main's page structure: action keys, create-form context, pending
proposal controls, and the soft write gate. The routes themselves stay in
``web_debts.py``; these builders keep view shaping out of the handlers.
"""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Request
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes.web_common import (
    _base_ctx,
    _home_amount_label,
    _minor_amount_value,
    _require_selected_ledger_write,
    _sidebar_counts,
)
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc

_PROPOSAL_STATUS_LABELS = {
    "pending": "待 TA 确认",
    "confirmed": "已确认",
    "partially_confirmed": "收了一部分",
    "rejected": "在对账",
    "withdrawn": "已撤回",
    "expired": "这次没对上",
    "superseded": "重记过了",
}
# 解决日期前缀 (mirror resolvedDateText)：confirmed 标「对上」、partial「收了一部分」、其余纯日期不加负面前缀。
_PROPOSAL_DATE_CONFIRMED = "{} 对上"
_PROPOSAL_DATE_PARTIAL = "{} 收了一部分"

# D3 表单契约：详情页「确认到账」金额输入的字段名 (区分同页申报表的 ``amount_major``，
# 与服务侧 ``confirmed_amount_cents`` 同名)。模板侧由 ``web_debts._render_debt_detail``
# 注入上下文渲染，路由侧由 ``web_debt_proposal_actions`` 以 ``Form(alias=...)`` 绑定——
# 两侧消费同一个常量而非各自写字面量，任一侧漂移都会被契约测试钉住。
PROPOSAL_CONFIRM_AMOUNT_FIELD = "confirmed_amount_major"
# N-1 兼容：D3 修复前路由误读的旧字段名。旧客户端/旧页面仍按它提交时不得静默丢金额
# (新字段非空优先，旧字段兜底，两者皆空按申报全额)；路由侧同样以 Form(alias=...) 绑定本常量。
PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY = "amount_major"


def _parse_paid_at(raw: str, timezone_name: str = "") -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        selected_date = date.fromisoformat(text)
    except ValueError as exc:
        raise AppError(
            "invalid_request",
            "请选择正确的还款日期。",
            status_code=422,
        ) from exc
    try:
        zone = ZoneInfo(timezone_name) if timezone_name else accounting_zone()
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise AppError("invalid_request", "原还款日期的时区无法读取，请核对后重新填写。", status_code=422) from exc
    return datetime.combine(selected_date, time.min, tzinfo=zone)


def _day_label(value) -> str:
    """日粒度日期 (accounting tz Asia/Shanghai)，去对账味 (镜像 Android displayDate 到「日」)。"""
    if value is None:
        return ""
    return value.astimezone(accounting_zone()).strftime("%Y-%m-%d")


def _proposal_pending_line(pending, viewer_is_debtor: bool | None) -> str:
    """Describe an unconfirmed repayment claim and the participant who should review it."""
    if viewer_is_debtor is True:
        return "你说你还了这一份，等家人确认一下"
    if viewer_is_debtor is False:
        amount = _home_amount_label(pending.proposed_amount_cents, pending.home_currency_code)
        return f"TA 申报已还 {amount}，请核对实际收到的金额"
    return "他们之间有一笔正在确认"


def _resolved_proposal_row(proposal) -> dict:
    """已解决 proposal 的沉降行：冻结额 + 可选备注 + 日粒度日期(带状态前缀) + neutral 状态标签。

    §3.4 已解决态一律 neutral (confirmed 不挑成 success/绿)、集合零汇总；rejected→「在对账」/ expired→
    「这次没对上」不读作失败 (永不 danger)。逐字镜像 ResolvedProposalRow + resolvedDateText。
    """
    day = _day_label(proposal.resolved_at or proposal.created_at)
    if proposal.status == "confirmed":
        date_text = _PROPOSAL_DATE_CONFIRMED.format(day)
    elif proposal.status == "partially_confirmed":
        date_text = _PROPOSAL_DATE_PARTIAL.format(day)
    else:
        date_text = day
    return {
        "amount_label": _home_amount_label(proposal.proposed_amount_cents, proposal.home_currency_code),
        "note": (proposal.note or "").strip() or None,
        "date_text": date_text,
        "status_label": _PROPOSAL_STATUS_LABELS.get(proposal.status, _PROPOSAL_STATUS_LABELS["pending"]),
    }


def _proposal_section(proposals, viewer_is_debtor: bool | None) -> dict:
    """Current proposal controls; settled records live in the paged activity view."""

    pending = next((p for p in proposals if p.status == "pending"), None)
    section = {
        "pending_line": _proposal_pending_line(pending, viewer_is_debtor) if pending else None,
        "has_resolved": any(p.status != "pending" for p in proposals),
        # 写面动作：债务人可发起(无 pending 时)/撤回(自己 pending 时)；债权人可确认/拒绝(对方 pending 时)。
        # pending 以视图行下送 (public_id + 金额标签)，模板与表单不再触碰原始行。
        "pending": (
            {
                "public_id": pending.public_id,
                "amount_label": _home_amount_label(pending.proposed_amount_cents, pending.home_currency_code),
                # 确认输入预填值 = 对方申报全额 (可改部分确认)；留空提交时服务端同按全额处理。
                "amount_value": _minor_amount_value(pending.proposed_amount_cents, pending.home_currency_code),
            }
            if pending
            else None
        ),
        "can_propose": viewer_is_debtor is True and pending is None,
        "can_withdraw": viewer_is_debtor is True and pending is not None,
        "can_confirm": viewer_is_debtor is False and pending is not None,
    }
    return section




# ── 写面 (slice C2：共享命令层的 Web 表单面，原生构建) ────────────────────────

_DEBT_KIND_OPTIONS = (
    ("one_off", "一次结清", "一次性往来，约定一次还清。"),
    ("revolving", "循环往来", "长期互相垫付，随还随续，没有固定期数。"),
    ("installment", "分期还款", "按期固定偿还，系统会为每一期排出计划。"),
)
_DEBT_DIRECTION_OPTIONS = (
    ("i_owe", "我欠 TA", "记一笔自己应付的。"),
    ("owed_to_me", "TA 欠我", "记一笔对方应付的。"),
)
_DEBT_ACTION_KEY_NAMES = (
    "repay",
    "adjust",
    "kind",
    "void",
    "forgive",
    "proposal_create",
    "proposal_withdraw",
    "proposal_confirm",
    "proposal_reject",
)


def _debt_action_keys() -> dict[str, str]:
    # 每次渲染一套新键：浏览器重复提交同一表单 = 同键幂等 HIT，刷新重填 = 新意图。
    return {name: str(uuid4()) for name in _DEBT_ACTION_KEY_NAMES}


def _debt_create_context(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    values: dict[str, str] | None = None,
    error: str | None = None,
) -> dict:
    """Render a creation intent without replacing its currency or retry key."""

    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="新建欠款",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["kind_options"] = [
        {"value": value, "label": label, "hint": hint}
        for value, label, hint in _DEBT_KIND_OPTIONS
    ]
    ctx["direction_options"] = [
        {"value": value, "label": label, "hint": hint}
        for value, label, hint in _DEBT_DIRECTION_OPTIONS
    ]
    home = ctx["home_currency_code"]
    from app.services.currency_common import supported_currency_codes

    ctx["currency_options"] = [home, *sorted(supported_currency_codes() - {home})]
    values = values or {}
    captured_home = values.get("home_currency_code", "")
    ctx["form_home_currency_code"] = captured_home if captured_home in supported_currency_codes() else home
    ctx["selected_currency_code"] = values.get("currency_code") or ctx["form_home_currency_code"]
    ctx["idempotency_key"] = values.get("idempotency_key") or str(uuid4())
    ctx["today"] = now_utc().astimezone(accounting_zone()).strftime("%Y-%m-%d")
    ctx["values"] = values
    ctx["form_error"] = error
    return ctx


def _debt_write_gate(options, selected_id: str) -> bool:
    try:
        _require_selected_ledger_write(options, selected_id)
    except AppError:
        return False
    return True

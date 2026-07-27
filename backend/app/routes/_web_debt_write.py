"""Write-surface context helpers for the /web/debts pages (slice C2).

Native to main's page structure: action keys, create-form context, repayment-fact
timeline rows, and the soft write gate. The routes themselves stay in
``web_debts.py``; these builders keep view shaping out of the handlers.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes.web_common import (
    _base_ctx,
    _currency_input_view,
    _home_amount_label,
    _minor_amount_value,
    _require_selected_ledger_write,
    _sidebar_counts,
)
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc

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
_PROPOSAL_HISTORY_COLLAPSED = 3  # 折叠时显示前 3 条，其余进 <details> (镜像 ResolvedHistoryCard 的 take(3))
# 解决日期前缀 (mirror resolvedDateText)：confirmed 标「对上」、partial「收了一部分」、其余纯日期不加负面前缀。
_PROPOSAL_DATE_CONFIRMED = "{} 对上"
_PROPOSAL_DATE_PARTIAL = "{} 收了一部分"

# D3 表单契约：详情页「确认到账」金额输入的字段名 (区分同页申报表的 ``amount_major``，
# 与服务侧 ``confirmed_amount_cents`` 同名)。模板侧由 ``web_debts._render_debt_detail``
# 注入上下文渲染，路由侧由 ``web_debt_proposal_actions`` 以 ``Form(alias=...)`` 绑定——
# 两侧消费同一个常量而非各自写字面量，任一侧漂移都会被契约测试钉住。
PROPOSAL_CONFIRM_AMOUNT_FIELD = "confirmed_amount_major"


def _day_label(value) -> str:
    """日粒度日期 (accounting tz Asia/Shanghai)，去对账味 (镜像 Android displayDate 到「日」)。"""
    if value is None:
        return ""
    return value.astimezone(accounting_zone()).strftime("%Y-%m-%d")


def _proposal_pending_line(pending, viewer_is_debtor: bool | None) -> str:
    """在途 proposal 的一行关系状态句 (「谁该接下一步」)。

    web 只读=描述非「立即确认」CTA：债务人侧「你说还了，等家人确认」、债权人侧「TA 说还了 ¥X，看看
    对不对」、第三方中性。**不复用** Android 的 debt_proposal_creditor_pending (那条带「确认一下吧」动作
    hint，web 没有确认钮、会误导)；确认/拒绝/撤回都在手机 App + /api。
    """
    if viewer_is_debtor is True:
        return "你说你还了这一份，等家人确认一下"
    if viewer_is_debtor is False:
        amount = _home_amount_label(pending.proposed_amount_cents, pending.home_currency_code)
        return f"TA 把 {amount} 那份给你啦，看看对不对"
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
    """收发箱视图模型：在途 pending 一行状态句 + 已解决「过往」沉降 + 动作可用性。

    显示层契约不变：在途 (≤1，one-pending-per-debt) 与已解决拆开，折叠前 3 + 其余 <details>，
    已解决逐行冻结额·neutral 状态·日粒度日期，集合零汇总，永不红。
    写面 (slice C2) 增加动作可用性字段 (can_propose/can_withdraw/can_confirm + pending 本体)，
    由服务端按角色与状态裁决，模板不推导；空箱也返回 dict (动作判定不依赖历史)。
    """

    pending = next((p for p in proposals if p.status == "pending"), None)
    resolved_rows = [_resolved_proposal_row(p) for p in proposals if p.status != "pending"]
    section = {
        "pending_line": _proposal_pending_line(pending, viewer_is_debtor) if pending else None,
        "history_title": _PROPOSAL_HISTORY_TITLE,
        "resolved_visible": resolved_rows[:_PROPOSAL_HISTORY_COLLAPSED],
        "resolved_hidden": resolved_rows[_PROPOSAL_HISTORY_COLLAPSED:],
        "history_expand_label": f"查看全部 {len(resolved_rows)} 条过往",
        "has_resolved": bool(resolved_rows),
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
    """新建欠款页上下文：币种感知的金额输入 + 每渲染一套幂等键。"""

    ctx = _base_ctx(
        request,
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
    ctx["currency_input"] = _currency_input_view(None)
    from app.services.currency_common import home_currency_code, supported_currency_codes

    home = home_currency_code()
    ctx["currency_options"] = [home, *sorted(supported_currency_codes() - {home})]
    ctx["idempotency_key"] = str(uuid4())
    ctx["today"] = now_utc().astimezone(accounting_zone()).strftime("%Y-%m-%d")
    ctx["values"] = values or {}
    ctx["form_error"] = error
    return ctx


def _fact_rows(facts_page) -> list[dict]:
    """还款事实时间线行：金额 + 日期 + 作废注记（读模型，只描述不裁决）。"""

    rows: list[dict] = []
    for fact in facts_page.items:
        void = fact.void_fact
        rows.append(
            {
                "amount_label": _home_amount_label(fact.amount_cents, facts_page.home_currency_code),
                "date_text": _day_label(fact.paid_at),
                "is_voided": fact.status == "voided",
                "void_reason": (void.reason or "").strip() if void else "",
                "void_date_text": _day_label(void.created_at) if void else "",
                "public_id": fact.public_id,
                # 每行独立幂等键 (撤销单条误记，重复提交同键 HIT)。
                "void_key": str(uuid4()),
            }
        )
    return rows


def _debt_write_gate(options, selected_id: str) -> bool:
    try:
        _require_selected_ledger_write(options, selected_id)
    except AppError:
        return False
    return True



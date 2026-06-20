"""/web 桌面账本 · 还债目标进度 (ADR-0049 债务域 web 面 slice 4).

只读：列出本账本的 ``debt_repayment`` 目标 + 清偿进度。镜像 Android ``DebtPlanProgress``：
成员/混装 = **件数英雄**(一格=一笔=一次两清)，金额成弱化副文案(成员永不带「欠」、混币整条
隐藏)；**仅纯外部目标**显 businesslike KPI(``three_state`` 琥珀非红 + 还清投影三态诚实)。
写动作(设/改还清日期、复核处理)全留 Android + ``/api``。

``composition``(Member/External/Mixed/Empty) **web 端从 ``linked_debts[].counterparty_type``
派生**(后端不序列化该枚举，逐字镜像 Android ``DebtGoalComposition``，含 Empty 短路)；KPI 块
gate ``== External``(用 ==External 而非 !=Member 以排除 Mixed)。成员债**永不 danger**(红线②)。
读路径走 ``list_debt_repayment_goals``(``persist_achievement=False``，viewer 读永不锁存)，纯只读。
成员行文案复用 ``web_debts`` 的 ``_MEMBER_*`` 标签(扩而非重写)；目标级文案逐字镜像
``strings_stats_budget.xml`` 的 ``debt_plan_*`` / ``debt_kpi_payoff*`` / ``debt_three_state_*``。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _home_amount_label,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.routes.web_debts import (
    _DIRECTION_LABELS,
    _MEMBER_STATUS,
    _STATUS_LABELS,
    _STATUS_TONE,
    _communal_ratio,
    _debt_name,
    _member_progress_note,
)
from app.schemas._goals import GoalResponse
from app.services.goal_debt_repayment_service import list_debt_repayment_goals

router = APIRouter(prefix="/web/debt-goals", tags=["web"])

# ── 派生成分 (镜像 Android DebtGoalComposition) ──
_COMPOSITION_EMPTY = "empty"
_COMPOSITION_MEMBER = "member"
_COMPOSITION_EXTERNAL = "external"
_COMPOSITION_MIXED = "mixed"

# evaluation_state → 徽章 (achieved→success/ok · not_evaluable→warn/amber · in_progress→info→web 中性)
_EVAL_LABELS = {"in_progress": "进行中", "achieved": "已达成", "not_evaluable": "待复核"}
_EVAL_TONE = {"in_progress": "", "achieved": "ok", "not_evaluable": "amber"}

# three_state → 徽章 (ahead→success/ok · on_track→info→web 中性 · at_risk→warn/amber，永不 danger，§7.0)
_THREE_STATE_LABELS = {"on_track": "按计划进行", "ahead": "比计划提前", "at_risk": "可能晚于计划"}
_THREE_STATE_TONE = {"ahead": "ok", "on_track": "", "at_risk": "amber"}

# 件数英雄 / 空态 / 复核 文案 (逐字镜像 strings_stats_budget.xml 的 debt_plan_* / debt_goal_*)
_PLAN_HEADLINE_MEMBER_START = "这几笔，和家人一起慢慢清"
_PLAN_HEADLINE_MEMBER_DONE = "这几笔，和家人都两清啦"
_PLAN_ALL_VOIDED = "关联的欠款都已作废"
_GOAL_INTRO = "跟踪关联欠款的清偿，全部还清即达成目标。"
_GOAL_EMPTY_TITLE = "还没有还债目标"
_GOAL_EMPTY_BODY = "把一笔或多笔欠款关联到目标后，这里会显示它们的清偿进度。"
_GOAL_LINKS_TITLE = "关联欠款"
# web 只读：描述性 note(非 CTA，无 ack/remove/archive 钮，复核处理在 App)，琥珀非红 (§6.5 去-shame)。
_GOAL_NEEDS_REVIEW = "某关联欠款被判无效，需要你拿个主意"
_GOAL_NEEDS_REVIEW_HINT = "复核与处理请在手机 App"

# 还清投影 3 臂 insufficient 臂 (逐字镜像 debt_kpi_payoff_unknown)
_KPI_PAYOFF_UNKNOWN = "还没有足够数据估算还清日期"

# 成员 per-link note (link 级，区别于 detail 关系主句；逐字镜像 debt_link_member_note_*)
_LINK_MEMBER_NOTE_CLEARED = "已两清"
_LINK_MEMBER_NOTE_VOIDED = "这件事不算了"


def _counted_links(evaluation: object) -> list:
    """计入进度的关联欠款：作废的不计入分子分母 (§6.2，镜像 countedLinks)。"""
    return [link for link in evaluation.linked_debts if link.status != "voided"]


def _goal_composition(counted: list) -> str:
    """成分 (镜像 DebtGoalComposition)：空 / 全成员 / 全外部 / 混装。

    ``any_external`` 用「非成员」判定 (镜像 Android ``counterpartyType != MEMBER``，非 ==external)。
    """
    if not counted:
        return _COMPOSITION_EMPTY
    any_member = any(link.counterparty_type == "member" for link in counted)
    any_external = any(link.counterparty_type != "member" for link in counted)
    if any_member and any_external:
        return _COMPOSITION_MIXED
    if any_member:
        return _COMPOSITION_MEMBER
    return _COMPOSITION_EXTERNAL


def _shared_currency(counted: list) -> str | None:
    """仅当所有计入欠款同一本位币才返回该币种，否则 None (金额副文案整条隐藏，镜像 sharedHomeCurrencyCode)。"""
    codes = {link.home_currency_code for link in counted}
    return next(iter(codes)) if len(codes) == 1 else None


def _plan_headline(composition: str, cleared: int, total: int, remaining: int) -> str:
    """件数主文案 (composition 自适应)。成员用 cleared+remaining；外部/混装用 cleared+total。"""
    if composition == _COMPOSITION_MEMBER:
        if cleared == 0:
            return _PLAN_HEADLINE_MEMBER_START
        if remaining == 0:
            return _PLAN_HEADLINE_MEMBER_DONE
        return f"和家人两清了 {cleared} 笔 · 还剩 {remaining} 笔"
    if composition == _COMPOSITION_EXTERNAL:
        return f"已还清 {cleared} / {total} 笔"
    return f"已处理 {cleared} / {total} 笔"  # mixed


def _plan_amount_line(
    composition: str, principal_sum: int, remaining_sum: int, remaining_count: int, currency: str
) -> str:
    """金额弱化副文案。成员永不带「欠」(用 共/还剩)；外部用 共/剩余。镜像 PlanAmountLine。"""
    total = _home_amount_label(principal_sum, currency)
    is_member = composition == _COMPOSITION_MEMBER
    if remaining_count == 0:
        return f"这几笔共 {total}" if is_member else f"共 {total}"
    remaining = _home_amount_label(remaining_sum, currency)
    if is_member:
        return f"这几笔共 {total} · 还剩 {remaining}"
    return f"共 {total} · 剩余 {remaining}"


def _payoff_line(evaluation: object) -> dict:
    """还清投影 4 臂 (镜像 payoffLineState)：velocity(中性) / §B 分期合约(中性) / stale(琥珀warn) / insufficient(中性)。

    projected_payoff_date 有值时：tracking_days 有 = velocity 外推(「按最近N天进度」)；tracking_days 为 None
    = §B 分期合约确定性还清日(「按分期合约」，非外推，不带速率措辞)。两者互斥。projected 缺而 days 有 →
    suppress-on-stale(琥珀，非红，不催不施压)；都缺 → insufficient。
    """
    payoff = evaluation.projected_payoff_date
    if payoff is not None:
        if evaluation.tracking_days is not None:
            text = f"按最近 {evaluation.tracking_days} 天的进度，预计 {payoff.year} 年 {payoff.month} 月前后还清"
        else:
            # §B: deterministic installment contract date (期数×周期), not a velocity extrapolation —
            # so no "按最近N天进度" framing. tracking_days is None exactly in this all-installment case.
            text = f"按分期合约，预计 {payoff.year} 年 {payoff.month} 月还清"
        return {"text": text, "tone": "neutral"}
    if evaluation.days_since_last_activity is not None:
        text = f"已 {evaluation.days_since_last_activity} 天没有更新，估算可能已过期"
        return {"text": text, "tone": "warn"}
    return {"text": _KPI_PAYOFF_UNKNOWN, "tone": "neutral"}


def _target_label(target_date: date | None) -> str | None:
    if target_date is None:
        return None
    return f"还清目标 {target_date.year} 年 {target_date.month} 月"


def _external_kpi_view(evaluation: object) -> dict:
    """纯外部目标 KPI 块：three_state 琥珀徽章(可选) + 还清目标日期(可选) + 投影 3 臂(必显)。"""
    kpi: dict = {"payoff": _payoff_line(evaluation)}
    if evaluation.three_state is not None:
        kpi["three_state_label"] = _THREE_STATE_LABELS.get(evaluation.three_state, "按计划进行")
        kpi["three_state_tone"] = _THREE_STATE_TONE.get(evaluation.three_state, "")
    target_label = _target_label(evaluation.target_date)
    if target_label is not None:
        kpi["target_label"] = target_label
    return kpi


def _link_fraction(link: object) -> float:
    """per-link 填充比例 = (本金-剩余)/本金，钳到 [0,1]，cleared 强制 1 (镜像 clearedFraction)。"""
    if link.status == "cleared":
        return 1.0
    return _communal_ratio(link.principal_amount_cents - link.remaining_amount_cents, link.principal_amount_cents)


def _member_link_note(link: object) -> str:
    """成员 per-link note：voided→这件事不算了 / cleared→已两清 / open→进度档语 (镜像 DebtGoalLinkNote 成员臂)。"""
    if link.status == "voided":
        return _LINK_MEMBER_NOTE_VOIDED
    if link.status == "cleared":
        return _LINK_MEMBER_NOTE_CLEARED
    return _member_progress_note(_link_fraction(link))


def _external_link_meta(link: object) -> str:
    """外部 per-link meta：应付/应收 · 剩余 X · 本金 Y (逐字镜像 debt_goal_link_meta)。"""
    direction = _DIRECTION_LABELS.get(link.direction, "应付")
    remaining = _home_amount_label(link.remaining_amount_cents, link.home_currency_code)
    principal = _home_amount_label(link.principal_amount_cents, link.home_currency_code)
    return f"{direction} · 剩余 {remaining} · 本金 {principal}"


def _goal_link_row(link: object) -> dict:
    """一行关联欠款 (镜像 DebtGoalLinkRow)：作废沉降无条；成员 note + neutral/success 永不 danger，
    外部 meta + open/cleared/voided 状态色(外部 voided 可 danger)。bar 仅 open/cleared 显示。"""
    is_member = link.counterparty_type == "member"
    is_voided = link.status == "voided"
    row: dict = {
        "name": _debt_name(link),
        "is_member": is_member,
        "recede": is_voided,
        "show_bar": not is_voided,
        "fraction_percent": int(round(_link_fraction(link) * 100)),
        "is_cleared": link.status == "cleared",
    }
    if is_member:
        status_label, status_tone = _MEMBER_STATUS.get(link.status, _MEMBER_STATUS["open"])
        row["status_label"] = status_label
        row["status_tone"] = status_tone  # 成员永不 danger (open/voided→neutral, cleared→ok)
        row["note"] = _member_link_note(link)
    else:
        row["status_label"] = _STATUS_LABELS.get(link.status, "未结清")
        row["status_tone"] = _STATUS_TONE.get(link.status, "")
        row["meta"] = _external_link_meta(link)
    return row


def _debt_goal_view(goal: GoalResponse) -> dict:
    """一个还债目标的渲染视图。total_count==0(全作废) 短路：只显 all_voided 文案 + 作废 link 行。"""
    evaluation = goal.debt_repayment
    counted = _counted_links(evaluation)
    composition = _goal_composition(counted)
    cleared = sum(1 for link in evaluation.linked_debts if link.status == "cleared")
    total = len(counted)
    remaining = total - cleared
    view: dict = {
        "name": goal.name,
        "public_id": goal.public_id,
        "eval_label": _EVAL_LABELS.get(evaluation.evaluation_state, "进行中"),
        "eval_tone": _EVAL_TONE.get(evaluation.evaluation_state, ""),
        "needs_review": evaluation.needs_review,
        "all_voided": total == 0,
        "cleared_count": cleared,
        "total_count": total,
        "links_title": _GOAL_LINKS_TITLE,
        "links": [_goal_link_row(link) for link in evaluation.linked_debts],
    }
    if total == 0:
        return view
    view["headline"] = _plan_headline(composition, cleared, total, remaining)
    view["fraction_percent"] = int(round(cleared * 100 / total))
    currency = _shared_currency(counted)
    if currency is not None:
        principal_sum = sum(link.principal_amount_cents for link in counted)
        remaining_sum = sum(link.remaining_amount_cents for link in counted)
        view["amount_line"] = _plan_amount_line(composition, principal_sum, remaining_sum, remaining, currency)
    if composition == _COMPOSITION_EXTERNAL:
        view["kpi"] = _external_kpi_view(evaluation)
    return view


@router.get("", response_class=HTMLResponse)
def web_debt_goals(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    goals = list_debt_repayment_goals(db, tenant_id=selected_id)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="还债目标",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["intro"] = _GOAL_INTRO
    ctx["goals"] = [_debt_goal_view(goal) for goal in goals]
    ctx["empty_title"] = _GOAL_EMPTY_TITLE
    ctx["empty_body"] = _GOAL_EMPTY_BODY
    ctx["all_voided_text"] = _PLAN_ALL_VOIDED
    ctx["needs_review_note"] = _GOAL_NEEDS_REVIEW
    ctx["needs_review_hint"] = _GOAL_NEEDS_REVIEW_HINT
    return templates.TemplateResponse(request=request, name="debt_goals.html", context=ctx)

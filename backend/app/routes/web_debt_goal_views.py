"""View-model and page-rendering helpers for Web debt goals."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.routes.web_common import (
    _base_ctx,
    _home_amount_label,
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
    _web_viewer_account_id,
)
from app.schemas._goals import GoalResponse
from app.services.debt_service import list_debts
from app.services.goal_debt_repayment_service import (
    list_debt_repayment_goals,
)

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
_GOAL_NEEDS_REVIEW = "某关联欠款被判无效，需要你拿个主意"
_GOAL_REVIEW_ACHIEVED = "目标已经达成；可以保留这次记录，也可以移除已经不算的欠款。"
_GOAL_REVIEW_NOT_EVALUABLE = "移除已经不算的欠款后，这个计划会按新的关联集合继续。"
_GOAL_REVIEW_ALL_VOIDED = "全部关联欠款都已不算；可以补充新的未结清欠款，或归档这个计划。"
_STALE_MESSAGE = "计划已在其它端更新，请刷新后重新操作。"
_CREATE_VALIDATION = "请输入目标名称并至少选择一笔未结清欠款。"

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

    未知类型保守落入 mixed，避免把不认识的数据误当成纯外部欠款并展示外部 KPI。
    """
    if not counted:
        return _COMPOSITION_EMPTY
    any_member = any(link.counterparty_type == "member" for link in counted)
    any_external = any(link.counterparty_type == "external" for link in counted)
    any_unknown = any(link.counterparty_type not in {"member", "external"} for link in counted)
    if any_unknown or (any_member and any_external):
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
        kpi["three_state_label"] = _THREE_STATE_LABELS.get(
            evaluation.three_state,
            "计划状态待确认",
        )
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
    if link.status == "open":
        return _member_progress_note(_link_fraction(link))
    return "状态变化待确认"


def _external_link_meta(link: object) -> str:
    """外部 per-link meta：应付/应收 · 剩余 X · 本金 Y (逐字镜像 debt_goal_link_meta)。"""
    direction = _DIRECTION_LABELS.get(link.direction, "方向待确认")
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
        "show_bar": link.status in {"open", "cleared"},
        "fraction_percent": int(round(_link_fraction(link) * 100)),
        "is_cleared": link.status == "cleared",
    }
    if is_member:
        status_label, status_tone = _MEMBER_STATUS.get(
            link.status,
            ("状态待确认", ""),
        )
        row["status_label"] = status_label
        row["status_tone"] = status_tone  # 成员永不 danger (open/voided→neutral, cleared→ok)
        row["note"] = _member_link_note(link)
    else:
        row["status_label"] = _STATUS_LABELS.get(link.status, "状态待确认")
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
        "row_version": goal.row_version,
        "is_archived": goal.status == "archived",
        "eval_label": _EVAL_LABELS.get(
            evaluation.evaluation_state,
            "目标状态待确认",
        ),
        "eval_tone": _EVAL_TONE.get(evaluation.evaluation_state, ""),
        "needs_review": evaluation.needs_review,
        "all_voided": total == 0,
        "cleared_count": cleared,
        "total_count": total,
        "links_title": _GOAL_LINKS_TITLE,
        "links": [_goal_link_row(link) for link in evaluation.linked_debts],
        "linked_debt_ids": [link.debt_public_id for link in evaluation.linked_debts],
        "non_voided_debt_ids": [link.debt_public_id for link in evaluation.linked_debts if link.status != "voided"],
        "composition": composition,
        "target_date_value": (evaluation.target_date.isoformat() if evaluation.target_date is not None else ""),
        "idempotency_keys": {
            "links": str(uuid4()),
            "target_date": str(uuid4()),
            "acknowledge": str(uuid4()),
            "remove_voided": str(uuid4()),
            "archive": str(uuid4()),
            "restore": str(uuid4()),
        },
    }
    view["can_set_target_date"] = composition == _COMPOSITION_EXTERNAL and not view["is_archived"]
    view["can_acknowledge_review"] = (
        evaluation.needs_review and evaluation.evaluation_state == "achieved" and not view["is_archived"]
    )
    view["can_remove_voided"] = (
        evaluation.needs_review and bool(view["non_voided_debt_ids"]) and not view["is_archived"]
    )
    if evaluation.needs_review:
        if evaluation.evaluation_state == "achieved":
            view["review_body"] = _GOAL_REVIEW_ACHIEVED
        elif view["non_voided_debt_ids"]:
            view["review_body"] = _GOAL_REVIEW_NOT_EVALUABLE
        else:
            view["review_body"] = _GOAL_REVIEW_ALL_VOIDED
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


def _debt_choice_view(debt: object) -> dict:
    is_member = debt.counterparty_type == "member"
    if is_member:
        status_label, status_tone = _MEMBER_STATUS.get(
            debt.status,
            ("状态待确认", ""),
        )
        meta = (
            _member_progress_note(
                _communal_ratio(
                    debt.paid_amount_cents,
                    debt.principal_amount_cents,
                )
            )
            if debt.status == "open"
            else status_label
        )
    else:
        status_label = _STATUS_LABELS.get(debt.status, "状态待确认")
        status_tone = _STATUS_TONE.get(debt.status, "")
        meta = _external_link_meta(debt)
    return {
        "public_id": debt.public_id,
        "name": _debt_name(debt),
        "status": debt.status,
        "status_label": status_label,
        "status_tone": status_tone,
        "is_member": is_member,
        "meta": meta,
    }


def _default_create_values() -> dict:
    return {
        "name": "",
        "selected_debt_ids": [],
        "idempotency_key": str(uuid4()),
    }


def _render_debt_goals(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    message: str | None = None,
    error: str | None = None,
    create_values: dict | None = None,
    link_values: dict[str, list[str]] | None = None,
    target_values: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    account_id = _web_viewer_account_id(request, db, selected_id)
    debt_items = list_debts(
        db,
        tenant_id=selected_id,
        viewer_account_id=account_id,
    ).items
    choices = [_debt_choice_view(item) for item in debt_items]
    goals = list_debt_repayment_goals(
        db,
        tenant_id=selected_id,
        include_archived=True,
    )
    goal_views = [_debt_goal_view(goal) for goal in goals]
    link_overrides = link_values or {}
    date_overrides = target_values or {}
    for goal in goal_views:
        selected = set(link_overrides.get(goal["public_id"], goal["linked_debt_ids"]))
        goal["link_choices"] = [
            {
                **choice,
                "selected": choice["public_id"] in selected,
            }
            for choice in choices
            if choice["status"] == "open" or choice["public_id"] in goal["linked_debt_ids"]
        ]
        if goal["public_id"] in date_overrides:
            goal["target_date_value"] = date_overrides[goal["public_id"]]
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="还债目标",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["intro"] = _GOAL_INTRO
    ctx["goals_active"] = [goal for goal in goal_views if not goal["is_archived"]]
    ctx["goals_archived"] = [goal for goal in goal_views if goal["is_archived"]]
    ctx["create_candidates"] = [choice for choice in choices if choice["status"] == "open"]
    ctx["create_values"] = create_values or _default_create_values()
    ctx["message"] = message
    ctx["error"] = error
    ctx["empty_title"] = _GOAL_EMPTY_TITLE
    ctx["empty_body"] = _GOAL_EMPTY_BODY
    ctx["all_voided_text"] = _PLAN_ALL_VOIDED
    ctx["needs_review_note"] = _GOAL_NEEDS_REVIEW
    return templates.TemplateResponse(
        request=request,
        name="debt_goals.html",
        context=ctx,
        status_code=status_code,
    )

"""/web Debt pages: viewer-personal payable list and role-aware detail.

slice 1: 只读欠款列表 (``GET /web/debts``)，镜像 Android ``DebtListScreen``。
slice 2a: 只读欠款详情 (``GET /web/debts/{public_id}``)，**按角色分轴**镜像 Android
``DebtDetailScreen`` —— 外部债走 businesslike 会计卡 (剩余/本金/已偿还/状态)，家庭(成员)
债走 communal 关系卡 (一起处理眉 + 无金额关系主句 + 件数进度 + 「看看账」展开，永不红)。

成员债的角色 (你帮我垫的 / 我帮你垫的 / 第三方) 由服务端权威字段 ``viewer_is_debtor`` 决定
(客户端不推导)，所以详情走 ``get_participant_debt_response`` —— 需要 viewer 的 account_id：
Web session 用会话账户，loopback owner-console 用账本 owner 账户。

slice 2b: 成员债的还款 proposal **状态 + 过往历史** (``list_repayment_proposals``，**无新端点**)。
在途 pending 渲染成一行**关系状态句** (「谁该接下一步」非「谁欠」，web 只读=描述非「立即确认」CTA)；
已解决 proposal 沉降进「过往」块 (冻结额·neutral 状态·日粒度日期·可选备注，集合零汇总，永不红)。

外部手工债务的事实命令由独立 ``web_debt_actions`` adapter 接入；成员债仍保持双方
proposal 流程，不在 Web 详情暴露单方面直写动作。
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _amount_segments,
    _base_ctx,
    _currency_input_view,
    _home_amount_label,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.routes.web_debt_form_views import (
    _DEBT_KIND_LABELS,
    _DEBT_KIND_OPTIONS,
    _debt_create_context,
    _repayment_fact_view,
)
from app.routes.web_debt_proposal_views import (
    _proposal_section,
)
from app.services.debt_service import (
    get_participant_debt_response,
    list_payables_for_account,
    list_repayment_facts,
    list_repayment_proposals,
)
from app.services.ledger_service import find_owner_account_id_for_ledger

router = APIRouter(prefix="/web", tags=["web"])

# 镜像 Android 债务标签词汇 (DebtGoalLabels.kt + strings_stats_budget.xml)，让 /web 与
# Android 渲染**同一套**中文 (三端 copy 同步)。外部债是会计向 应付/应收 (列表对成员/外部统一)。
_DIRECTION_LABELS = {"i_owe": "应付", "owed_to_me": "应收"}
_STATUS_LABELS = {"open": "未结清", "cleared": "已结清", "voided": "已作废"}
# 外部债状态色调镜像 debtLinkStatusTone：cleared→ok(成功)、voided→danger、open→neutral。
_STATUS_TONE = {"open": "", "cleared": "ok", "voided": "danger"}
# 无 counterparty_label 时的回退名 (debt_goal_counterparty_member / _external)。
_COUNTERPARTY_FALLBACK = {"member": "家庭成员", "external": "外部欠款"}
# ── 成员债 communal 文案 (slice 8e，逐字 port 自 MemberDebtLabels.kt + strings_stats_budget.xml) ──
_MEMBER_NEAR_RATIO = 0.7  # ratio≥0.7 = 快两清档
_MEMBER_SOME_RATIO = 0.5  # ratio≤0.5 = 对上一部分档
# 方向 (viewer-relative，§2.3)：True=债务人、False=债权人、None=第三方。
_MEMBER_DIRECTION = {True: "你帮我垫的", False: "我帮你垫的", None: "TA 们之间的一件事"}
_MEMBER_EYEBROW = "一起处理 · {}"
_MEMBER_EYEBROW_THIRD = "他们的一件事 · {}"
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
_MEMBER_PROGRESS_NOTE = {"none": "还没开始对账", "some": "已经对上一部分", "most": "这件事已对上大半"}
# 成员债状态徽章：cleared→success，其余(open/voided)→neutral，**永不 danger/红** (红线②)。
_MEMBER_STATUS = {"open": ("进行中", ""), "cleared": ("已两清", "ok"), "voided": ("已不算", "")}


def _is_member_view(debt) -> bool:
    """成员债行 (communal) 判定，镜像 :func:`_detail_view` 的 FX 防御：外币成员债退回外部
    会计行 (「无金额关系主句 + 单币进度」在多币种下崩)。slice 4 已把 bill_split 成员债冻结成
    home-shape，故外币成员实际罕见，此处是防御 + 与详情一致(列表点进详情同一根轴)。"""
    is_foreign = bool(debt.original_currency_code) and debt.original_currency_code != debt.home_currency_code
    return debt.counterparty_type == "member" and not is_foreign


def _debt_name(debt) -> str:
    return (debt.counterparty_label or "").strip() or _COUNTERPARTY_FALLBACK.get(
        debt.counterparty_type, _COUNTERPARTY_FALLBACK["external"]
    )


def _debt_view(debt) -> dict:
    """列表行视图模型 (slice 1A：按角色分轴)。

    外部债 = businesslike 会计行 (应付/应收 + 本位币剩余 editorial 拆分英雄 + 本金脚注 + 状态色含
    danger)。成员债 = communal 关系行 (对手方名 + viewer-相对关系主句〔无金额、永不应付应收剩余〕 +
    open 时细 success 进度条 + 状态徽章〔neutral/success **永不 danger** 红线②〕)，作废/已结清沉降。

    成员行的角色 (你帮我垫的/我帮你垫的/第三方) 读服务端权威 ``debt.viewer_is_debtor`` (由
    ``list_debts(viewer_account_id=)`` per-row 算)，**不**从 owner-相对 ``direction`` 推 (会对非当事方
    viewer 翻错)、**不**客户端推导 (红线⑥)。关系主句逐字复用详情的 :func:`_member_headline` (列表↔详情
    同一句，点进详情不变脸)。
    """
    is_member = _is_member_view(debt)
    view: dict = {
        "public_id": debt.public_id,
        "name": _debt_name(debt),
        "is_member": is_member,
        "status": debt.status,
    }
    if is_member:
        ratio = _communal_ratio(debt.paid_amount_cents, debt.principal_amount_cents)
        member_status_label, member_status_tone = _MEMBER_STATUS.get(debt.status, _MEMBER_STATUS["open"])
        view.update(
            {
                # 关系主句逐字复用详情 headline (无金额)；列表与详情同一句。
                "member_headline": _member_headline(debt.viewer_is_debtor, debt.status, debt.is_forgiven, ratio),
                "show_progress": debt.status == "open",
                "ratio_percent": int(round(ratio * 100)),
                "progress_note": _member_progress_note(ratio),
                "member_status_label": member_status_label,
                "member_status_tone": member_status_tone,
                # 作废/已结清的家人行视觉沉降 (淡出、永不红 — 红线② + 「办完可追溯」P1·已决)。
                "recede": debt.status != "open",
            }
        )
    else:
        view.update(
            {
                "direction_label": _DIRECTION_LABELS.get(debt.direction, "应付"),
                "status_label": _STATUS_LABELS.get(debt.status, "未结清"),
                "status_tone": _STATUS_TONE.get(debt.status, ""),
                # remaining_label: full string for the row's aria-label (the visible hero is the
                # editorial cur/int/dec split below). principal stays a plain muted footnote.
                "remaining_label": _home_amount_label(debt.remaining_amount_cents, debt.home_currency_code),
                "remaining_segments": _amount_segments(debt.remaining_amount_cents, debt.home_currency_code),
                "principal_label": _home_amount_label(debt.principal_amount_cents, debt.home_currency_code),
            }
        )
    return view


# 行内排序：未结清在前，已结清/作废沉到底 (active-first，镜像 Android groupDebtsForList)。
# Python sort 稳定 → 同档内保留 list_debts 的 created_at 次序。
_STATUS_RANK = {"open": 0, "cleared": 1, "voided": 2}


def _split_debt_views(items) -> tuple[list[dict], list[dict]]:
    """把债务列表分成 (家人, 外部) 两组，各组 active-first 排序 (1A 软分组)。

    家人在前 (section header 非 tab，单滚动列表)；禁列表级聚合记分牌 (无 per-person/终身总额)。
    """
    views = [_debt_view(debt) for debt in items]
    members = sorted((v for v in views if v["is_member"]), key=lambda v: _STATUS_RANK.get(v["status"], 0))
    externals = sorted((v for v in views if not v["is_member"]), key=lambda v: _STATUS_RANK.get(v["status"], 0))
    return members, externals


def _communal_ratio(paid_cents: int, principal_cents: int) -> float:
    """进度比例 = paid/principal，钳到 [0,1] (服务端冻结值，不读活余额，镜像 communalRatio)。"""
    if principal_cents <= 0:
        return 0.0
    return max(0.0, min(1.0, paid_cents / principal_cents))


def _member_headline(viewer_is_debtor: bool | None, status: str, is_forgiven: bool, ratio: float) -> str:
    """关系主句 (无金额)，逐字镜像 memberDebtHeadlineRes 的分派树。"""
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
    # open：按进度比例分三档 (viewer_is_debtor 在此已非空)。
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
    """§B 外部 installment 债详情的分期卡视图模型；非「进行中 + 已排期 installment」返回 None（不渲染卡）。

    镜像 Android ``DebtInstallmentCard`` + ``shouldShowInstallmentCard``（isOpen && isInstallmentScheduled）：
    合约还清日（措辞与 ``web_debt_goals._payoff_line`` 的「按分期合约」臂、Android ``debt_installment_payoff``
    逐字一致——三端同步）/ 已还期数**中性**进度（绝不基于 paid==count 宣称「已还清」，提额调整会让 N/N 而剩余
    仍 >0，完成由 status==cleared 决定，故卡只对 open 渲染）/ 每期**无息**估算（本金÷期数，floor，标「估算不含手续费」）。
    """
    count = debt.installment_count
    if debt.debt_kind != "installment" or count is None or debt.status != "open":
        return None
    period = debt.installment_period_months
    schedule = f"共 {count} 期 · 每月一期" if period in (None, 1) else f"共 {count} 期 · 每 {period} 个月一期"
    paid = min(debt.installment_paid_count or 0, count)
    payoff = debt.installment_payoff_date
    per_period_cents = debt.principal_amount_cents // count
    return {
        "schedule_label": schedule,
        "progress_label": f"已还 {paid} / {count} 期",
        "payoff_label": (f"按分期合约，预计 {payoff.year} 年 {payoff.month} 月还清" if payoff is not None else None),
        "per_period_label": f"每期约 {_home_amount_label(per_period_cents, home)} · 估算不含手续费",
    }


def _detail_view(debt) -> dict:
    """详情页视图模型 (slice 2a)，按角色分轴。

    外币成员债 (original_currency_code 异于本位币) 退回外部会计卡 —— 「无金额关系主句 +
    单币进度」语义在多币种下崩 (FX defense)；外部债恒走会计卡。slice 4 已把 bill_split 成员债
    冻结成 home-shape，故成员外币实际罕见，此处是防御。
    """
    home = debt.home_currency_code
    is_foreign = bool(debt.original_currency_code) and debt.original_currency_code != home
    use_member = debt.counterparty_type == "member" and not is_foreign
    name = (debt.counterparty_label or "").strip() or _COUNTERPARTY_FALLBACK.get(
        debt.counterparty_type, _COUNTERPARTY_FALLBACK["external"]
    )
    status = debt.status
    direct_writable = not use_member and debt.counterparty_type == "external" and debt.source_type == "manual"
    view = {
        "public_id": debt.public_id,
        "name": name,
        "is_member": use_member,
        "is_voided": status == "voided",
        "row_version": debt.row_version,
        "can_direct_mutate": direct_writable and status == "open",
        "can_void_repayment": direct_writable and status != "voided",
        **_currency_input_view(home),
        "principal_label": _home_amount_label(debt.principal_amount_cents, home),
        "paid_label": _home_amount_label(debt.paid_amount_cents, home),
    }
    if use_member:
        viewer_is_debtor = debt.viewer_is_debtor
        ratio = _communal_ratio(debt.paid_amount_cents, debt.principal_amount_cents)
        eyebrow = _MEMBER_EYEBROW_THIRD if viewer_is_debtor is None else _MEMBER_EYEBROW
        member_status_label, member_status_tone = _MEMBER_STATUS.get(status, _MEMBER_STATUS["open"])
        view.update(
            {
                "direction_subtitle": _MEMBER_DIRECTION[viewer_is_debtor],
                "eyebrow": eyebrow.format(name),
                "headline": _member_headline(viewer_is_debtor, status, debt.is_forgiven, ratio),
                "show_progress": status == "open",
                "ratio_percent": int(round(ratio * 100)),
                "progress_note": _member_progress_note(ratio),
                "member_status_label": member_status_label,
                "member_status_tone": member_status_tone,
                "can_forgive": viewer_is_debtor is False and status == "open",
            }
        )
    else:
        # External = businesslike accounting card: remaining as an editorial hero
        # (cur/int/dec split) + a thin neutral repayment bar (paid/principal). The
        # bar's ratio reuses _communal_ratio — same clamp(paid/principal) arithmetic,
        # rendered businesslike (--text-default fill, not the communal success green).
        view.update(
            {
                "direction_subtitle": _DIRECTION_LABELS.get(debt.direction, "应付"),
                "status_label": _STATUS_LABELS.get(status, "未结清"),
                "status_tone": _STATUS_TONE.get(status, ""),
                "debt_kind": debt.debt_kind,
                "debt_kind_label": _DEBT_KIND_LABELS.get(
                    debt.debt_kind,
                    _DEBT_KIND_LABELS["unspecified"],
                ),
                "debt_kind_options": _DEBT_KIND_OPTIONS,
                "remaining_segments": _amount_segments(debt.remaining_amount_cents, home),
                "paid_ratio_percent": int(
                    round(_communal_ratio(debt.paid_amount_cents, debt.principal_amount_cents) * 100)
                ),
                # §B 分期计划卡（仅进行中 + 已排期 installment 外部债非 None；镜像 Android 详情屏）。
                "installment": _installment_view(debt, home),
            }
        )
    return view


def _web_viewer_account_id(request: Request, db: Session, ledger_id: str) -> int | None:
    """The viewer's account for participant-scoped reads on /web.

    Web session (public host) → the paired account; loopback owner-console → the
    selected ledger's owner account. ``viewer_is_debtor`` is computed against this
    so the member-debt relational headline is right for whoever is looking.
    """
    session_auth = getattr(request.state, "web_session_auth", None)
    if session_auth is not None:
        return session_auth.account_id
    return find_owner_account_id_for_ledger(db, ledger_id=ledger_id)


@router.get("/debts", response_class=HTMLResponse)
def web_debts(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _web_viewer_account_id(request, db, selected_id)
    listing = (
        list_payables_for_account(
            db,
            tenant_id=selected_id,
            account_id=account_id,
        )
        if account_id is not None
        else None
    )
    items = listing.items if listing is not None else []
    member_debts, external_debts = _split_debt_views(items)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="我欠",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["member_debts"] = member_debts
    ctx["external_debts"] = external_debts
    return templates.TemplateResponse(request=request, name="debts.html", context=ctx)


@router.get("/debts/new", response_class=HTMLResponse)
def web_new_debt(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    ctx = _debt_create_context(
        request,
        db,
        options=options,
        selected_id=selected_id,
    )
    return templates.TemplateResponse(request=request, name="debt_new.html", context=ctx)


@router.get("/debts/{public_id}", response_class=HTMLResponse)
def web_debt_detail(
    request: Request,
    public_id: str,
    ledger_id: str | None = None,
    msg: str | None = None,
    flash_type: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _web_viewer_account_id(request, db, selected_id)
    # Participant-scoped (§5.2): gives the server-authoritative viewer_is_debtor + is_forgiven,
    # and raises debt_not_found (→ 404 HTML) when the debt isn't in this ledger / viewer.
    debt = get_participant_debt_response(db, public_id=public_id, ledger_id=selected_id, account_id=account_id)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠款详情",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    detail = _detail_view(debt)
    ctx["debt"] = detail
    ctx["flash_message"] = msg or ""
    ctx["flash_type"] = flash_type if flash_type in {"success", "error"} else ""
    action_keys: dict[str, str] = {}
    if detail["can_direct_mutate"]:
        action_keys.update(
            repayment=str(uuid4()),
            adjustment=str(uuid4()),
            void=str(uuid4()),
            kind=str(uuid4()),
        )
    if detail.get("can_forgive"):
        action_keys["forgive"] = str(uuid4())
    ctx["action_keys"] = action_keys
    if detail["is_member"]:
        detail["return_path"] = "/web/debts" if debt.viewer_is_debtor is not False else "/web/receivables"
    else:
        detail["return_path"] = "/web/debts" if debt.direction == "i_owe" else "/web/receivables"
    # Member proposal inbox: server-authoritative role actions + pending state +
    # resolved history. A loopback ledger without an active owner has no actor, so
    # it remains a read-only relationship view.
    proposals = None
    if detail["is_member"] and account_id is not None:
        items = list_repayment_proposals(
            db, tenant_id=selected_id, actor_account_id=account_id, public_id=public_id
        ).items
        proposals = _proposal_section(
            items,
            debt.viewer_is_debtor,
            debt_status=debt.status,
        )
        action_keys.update(
            proposal_create=str(uuid4()),
            proposal_withdraw=str(uuid4()),
            proposal_confirm=str(uuid4()),
            proposal_reject=str(uuid4()),
        )
    ctx["proposals"] = proposals
    history = None
    if account_id is not None:
        facts = list_repayment_facts(
            db,
            tenant_id=selected_id,
            actor_account_id=account_id,
            public_id=public_id,
            page=1,
            page_size=100,
        )
        history = {
            "items": [_repayment_fact_view(item, home_currency=facts.home_currency_code) for item in facts.items],
            "shown": len(facts.items),
            "total": facts.total,
        }
    ctx["repayment_history"] = history
    return templates.TemplateResponse(request=request, name="debt_detail.html", context=ctx)

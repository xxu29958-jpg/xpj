"""/web/debts pages (ADR-0049 债务域 · web 面 slice 1 + 2a + 2b).

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

**纯只读**：记账/还款/调整/作废/成员还款确认全部留 Android + ``/api``。文案逐字镜像 Android
``MemberDebtLabels`` + ``ResolvedHistoryCard`` + ``strings_stats_budget.xml`` (§14 三端 copy 同步)；
pending 状态行是 web 特定描述性文案 (Android 的是带「确认一下吧」动作 hint，web 无确认钮会误导)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes._web_debt_write import (
    PROPOSAL_CONFIRM_AMOUNT_FIELD,
    _debt_action_keys,
    _debt_create_context,
    _debt_write_gate,
    _fact_rows,
    _proposal_section,
)
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
from app.routes.web_debt_presenters import (
    _action_feedback_context,
    _communal_ratio,
    _installment_view,
    _member_headline,
    _member_progress_note,
    _proposal_feedback_context,
)
from app.services.debt_service import (
    get_participant_debt_response,
    list_debts,
    list_repayment_facts,
    list_repayment_proposals,
)
from app.services.ledger_service import find_owner_account_id_for_ledger
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc

router = APIRouter(prefix="/web", tags=["web"])

# 镜像 Android 债务标签词汇 (DebtGoalLabels.kt + strings_stats_budget.xml)，让 /web 与
# Android 渲染**同一套**中文 (三端 copy 同步)。外部债是会计向 应付/应收 (列表对成员/外部统一)。
_DIRECTION_LABELS = {"i_owe": "应付", "owed_to_me": "应收"}
_STATUS_LABELS = {"open": "未结清", "cleared": "已结清", "voided": "已作废"}
# 外部债状态色调镜像 debtLinkStatusTone：cleared→ok(成功)、voided→danger、open→neutral。
_STATUS_TONE = {"open": "", "cleared": "ok", "voided": "danger"}
# 无 counterparty_label 时的回退名 (debt_goal_counterparty_member / _external)。
_COUNTERPARTY_FALLBACK = {"member": "家庭成员", "external": "外部欠款"}
# 详情页类型徽章 (三端同词：installment=分期还款，与 web 新建页及 Android 详情屏同步)。
_DEBT_KIND_DETAIL_LABELS = {
    "one_off": "一次结清",
    "revolving": "循环往来",
    "installment": "分期还款",
    "unspecified": "暂不指定",
}

# 方向 (viewer-relative，§2.3)：True=债务人、False=债权人、None=第三方。
_MEMBER_DIRECTION = {True: "你帮我垫的", False: "我帮你垫的", None: "TA 们之间的一件事"}
_MEMBER_EYEBROW = "一起处理 · {}"
_MEMBER_EYEBROW_THIRD = "他们的一件事 · {}"
# 成员债状态徽章：cleared→success，其余(open/voided)→neutral，**永不 danger/红** (红线②)。
_MEMBER_STATUS = {"open": ("进行中", ""), "cleared": ("已两清", "ok"), "voided": ("已不算", "")}

# ── slice 2b: 成员 proposal 状态 + 过往历史 (复用 list_repayment_proposals，无新端点) ──
# 已解决态状态标签 + 日期前缀 + 标题/折叠 逐字镜像 strings_stats_budget.xml (debt_proposal_status_* /
# debt_proposal_history_*，§14 三端 copy 同步)；rejected→「在对账」(不读作失败)、voided/expired 永不 danger。
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
                "member_headline": _member_headline(
                    debt.viewer_is_debtor, debt.status, debt.is_forgiven, ratio
                ),
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
                "remaining_label": _home_amount_label(
                    debt.remaining_amount_cents, debt.home_currency_code
                ),
                "remaining_segments": _amount_segments(
                    debt.remaining_amount_cents, debt.home_currency_code
                ),
                "principal_label": _home_amount_label(
                    debt.principal_amount_cents, debt.home_currency_code
                ),
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
    members = sorted(
        (v for v in views if v["is_member"]), key=lambda v: _STATUS_RANK.get(v["status"], 0)
    )
    externals = sorted(
        (v for v in views if not v["is_member"]), key=lambda v: _STATUS_RANK.get(v["status"], 0)
    )
    return members, externals


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
    view = {
        "public_id": debt.public_id,
        "name": name,
        "is_member": use_member,
        "note": debt.note,
        "is_voided": status == "voided",
        "debt_kind": debt.debt_kind,
        # External keeps the editorial split hero; member detail uses one quiet exact
        # remaining label inside "看看账" rather than inventing another fold.
        "principal_label": _home_amount_label(debt.principal_amount_cents, home),
        "paid_label": _home_amount_label(debt.paid_amount_cents, home),
        "remaining_label": _home_amount_label(debt.remaining_amount_cents, home),
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
                "kind_label": _DEBT_KIND_DETAIL_LABELS.get(debt.debt_kind, "暂不指定"),
                "status_label": _STATUS_LABELS.get(status, "未结清"),
                "status_tone": _STATUS_TONE.get(status, ""),
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
    # viewer_is_debtor per row is server-authoritative: the web viewer (web-session account /
    # loopback owner) may not be a member Debt's debtor or creditor, so the communal row frames
    # the relationship from this viewer's side, not the stored owner-relative direction (§3.2).
    account_id = _web_viewer_account_id(request, db, selected_id)
    listing = list_debts(db, tenant_id=selected_id, viewer_account_id=account_id)
    member_debts, external_debts = _split_debt_views(listing.items)
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠款",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["can_write"] = _debt_write_gate(options, selected_id)
    ctx["member_debts"] = member_debts
    ctx["external_debts"] = external_debts
    return templates.TemplateResponse(request=request, name="debts.html", context=ctx)


@router.get("/debts/new", response_class=HTMLResponse)
def web_debt_new(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    return templates.TemplateResponse(
        request=request,
        name="debt_new.html",
        context=_debt_create_context(request, db, options=options, selected_id=selected_id),
    )


def _load_debt_detail_state(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    public_id: str,
) -> tuple[dict, object, int | None, list]:
    account_id = _web_viewer_account_id(request, db, selected_id)
    debt = get_participant_debt_response(
        db,
        public_id=public_id,
        ledger_id=selected_id,
        account_id=account_id,
    )
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠款详情",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    detail = _detail_view(debt)
    can_write = _debt_write_gate(options, selected_id)
    action_keys = _debt_action_keys() if can_write and debt.status == "open" else {}
    proposals = None
    proposal_items = []
    if detail["is_member"] and account_id is not None:
        proposal_items = list_repayment_proposals(
            db,
            tenant_id=selected_id,
            actor_account_id=account_id,
            public_id=public_id,
        ).items
        proposals = _proposal_section(proposal_items, debt.viewer_is_debtor)
    ctx.update(
        {
            "debt": detail,
            "can_write": can_write,
            "debt_open": debt.status == "open",
            "action_keys": action_keys,
            "can_change_member_kind": bool(
                can_write
                and debt.status == "open"
                and detail["is_member"]
                and debt.ledger_id is not None
                and debt.viewer_is_debtor is True
            ),
            "proposals": proposals,
            "pending_proposal": proposals["pending"] if proposals else None,
            "viewer_is_debtor": debt.viewer_is_debtor,
            "currency_input": _currency_input_view(debt.home_currency_code),
            "expected_row_version": debt.row_version,
        }
    )
    return ctx, debt, account_id, proposal_items


def _repayment_fact_rows(
    db: Session,
    *,
    selected_id: str,
    account_id: int | None,
    public_id: str,
) -> list[dict]:
    if account_id is None:
        return []
    return _fact_rows(
        list_repayment_facts(
            db,
            tenant_id=selected_id,
            actor_account_id=account_id,
            public_id=public_id,
            page=1,
            page_size=20,
        )
    )


def _render_debt_detail(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    public_id: str,
    confirm_amount_error: str | None = None,
    confirm_amount_value: str | None = None,
    confirm_error_proposal_id: str | None = None,
    action_kind: str | None = None,
    action_error: str | None = None,
    action_draft: dict[str, str] | None = None,
    action_target_public_id: str | None = None,
    action_conflict: bool = False,
    flash_message: str = "",
    flash_type: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    """详情页唯一渲染入口：GET 与 proposal 确认 422 原地重渲染共用 (照
    ``web_repayment_drafts._render_repayment_drafts`` 同页重渲染范式)，保证错误重渲染
    与正常渲染的页面结构零漂移。"""
    ctx, debt, account_id, proposal_items = _load_debt_detail_state(
        request,
        db,
        options=options,
        selected_id=selected_id,
        public_id=public_id,
    )
    ctx["proposal_confirm_amount_field"] = PROPOSAL_CONFIRM_AMOUNT_FIELD
    ctx.update(
        _proposal_feedback_context(
            proposal_items,
            confirm_amount_error=confirm_amount_error,
            confirm_amount_value=confirm_amount_value,
            confirm_error_proposal_id=confirm_error_proposal_id,
            currency_symbol=ctx["currency_input"]["currency_symbol"],
            status_code=status_code,
        )
    )
    ctx.update(
        _action_feedback_context(
            action_keys=ctx["action_keys"],
            can_write=ctx["can_write"],
            debt_status=debt.status,
            action_kind=action_kind,
            action_error=action_error,
            action_draft=action_draft,
            action_target_public_id=action_target_public_id,
            action_conflict=action_conflict,
            currency_symbol=ctx["currency_input"]["currency_symbol"],
            flash_message=flash_message,
            flash_type=flash_type,
        )
    )
    ctx["today"] = now_utc().astimezone(accounting_zone()).strftime("%Y-%m-%d")
    ctx["repayment_facts"] = _repayment_fact_rows(
        db,
        selected_id=selected_id,
        account_id=account_id,
        public_id=public_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="debt_detail.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/debts/{public_id}", response_class=HTMLResponse)
def web_debt_detail(
    request: Request,
    public_id: str,
    ledger_id: str | None = None,
    msg: str = "",
    flash_type: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _render_debt_detail(
        request,
        db,
        options=options,
        selected_id=selected_id,
        public_id=public_id,
        flash_message=msg,
        flash_type=flash_type,
    )

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
from app.routes.web_common import (
    LocalOnly,
    _amount_segments,
    _base_ctx,
    _home_amount_label,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.services.debt_service import (
    get_participant_debt_response,
    list_debts,
    list_repayment_proposals,
)
from app.services.ledger_service import find_owner_account_id_for_ledger
from app.services.spending_contract_service import accounting_zone

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
            f"按分期合约，预计 {payoff.year} 年 {payoff.month} 月还清" if payoff is not None else None
        ),
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
    view = {
        "public_id": debt.public_id,
        "name": name,
        "is_member": use_member,
        "is_voided": status == "voided",
        # remaining 在详情走 editorial 拆分英雄(外部 remaining_segments) / 成员卡无金额英雄,
        # 故详情不需要成串 remaining_label(列表行的 aria-label 才用,见 _debt_view)。
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
                "remaining_segments": _amount_segments(debt.remaining_amount_cents, home),
                "paid_ratio_percent": int(
                    round(_communal_ratio(debt.paid_amount_cents, debt.principal_amount_cents) * 100)
                ),
                # §B 分期计划卡（仅进行中 + 已排期 installment 外部债非 None；镜像 Android 详情屏）。
                "installment": _installment_view(debt, home),
            }
        )
    return view


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


def _proposal_section(proposals, viewer_is_debtor: bool | None) -> dict | None:
    """收发箱视图模型：在途 pending 一行状态句 + 已解决「过往」沉降 (折叠前 3 + 其余 <details>)。

    在途 pending (≤1，one-pending-per-debt) 与已解决拆开 (§3.2 pending 不进历史，避免一件事出现两次)；
    都为空则整段不渲染 (返回 None)。``proposals`` 是 list_repayment_proposals 的 newest-first 列表。
    """
    pending = next((p for p in proposals if p.status == "pending"), None)
    resolved_rows = [_resolved_proposal_row(p) for p in proposals if p.status != "pending"]
    if pending is None and not resolved_rows:
        return None
    return {
        "pending_line": _proposal_pending_line(pending, viewer_is_debtor) if pending else None,
        "history_title": _PROPOSAL_HISTORY_TITLE,
        "resolved_visible": resolved_rows[:_PROPOSAL_HISTORY_COLLAPSED],
        "resolved_hidden": resolved_rows[_PROPOSAL_HISTORY_COLLAPSED:],
        # 「查看全部 N 条过往」N=已解决总数 (展开后前 3 + 其余 = 全部 N 可见，镜像 Android expand 文案)。
        # 折叠走原生 <details> + CSS chevron 旋转 (无 JS)；不带「收起」文案——Android 那条是 JS toggle
        # 才需翻转按钮文字，web 的 summary 文本在两态一致、靠 chevron 指示展开/收起。
        "history_expand_label": f"查看全部 {len(resolved_rows)} 条过往",
        "has_resolved": bool(resolved_rows),
    }


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
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠款",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["member_debts"] = member_debts
    ctx["external_debts"] = external_debts
    return templates.TemplateResponse(request=request, name="debts.html", context=ctx)


@router.get("/debts/{public_id}", response_class=HTMLResponse)
def web_debt_detail(
    request: Request,
    public_id: str,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _web_viewer_account_id(request, db, selected_id)
    # Participant-scoped (§5.2): gives the server-authoritative viewer_is_debtor + is_forgiven,
    # and raises debt_not_found (→ 404 HTML) when the debt isn't in this ledger / viewer.
    debt = get_participant_debt_response(
        db, public_id=public_id, ledger_id=selected_id, account_id=account_id
    )
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠款详情",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    detail = _detail_view(debt)
    ctx["debt"] = detail
    # slice 2b: member proposal status + sunk 过往 history (read-only; reuses list_repayment_proposals,
    # no new endpoint). Only for the communal member card (use_member) with a resolvable viewer account
    # (loopback ledger with no active owner → account_id None → skip). The viewer here is already a
    # participant (get_participant_debt_response admitted them above), so list never re-404s.
    proposals = None
    if detail["is_member"] and account_id is not None:
        items = list_repayment_proposals(
            db, tenant_id=selected_id, actor_account_id=account_id, public_id=public_id
        ).items
        proposals = _proposal_section(items, debt.viewer_is_debtor)
    ctx["proposals"] = proposals
    return templates.TemplateResponse(request=request, name="debt_detail.html", context=ctx)

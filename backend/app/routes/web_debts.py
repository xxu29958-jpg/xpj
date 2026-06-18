"""/web/debts pages (ADR-0049 债务域 · web 面 slice 1 + 2a).

slice 1: 只读欠款列表 (``GET /web/debts``)，镜像 Android ``DebtListScreen``。
slice 2a: 只读欠款详情 (``GET /web/debts/{public_id}``)，**按角色分轴**镜像 Android
``DebtDetailScreen`` —— 外部债走 businesslike 会计卡 (剩余/本金/已偿还/状态)，家庭(成员)
债走 communal 关系卡 (一起处理眉 + 无金额关系主句 + 件数进度 + 「看看账」展开，永不红)。

成员债的角色 (你帮我垫的 / 我帮你垫的 / 第三方) 由服务端权威字段 ``viewer_is_debtor`` 决定
(客户端不推导)，所以详情走 ``get_participant_debt_response`` —— 需要 viewer 的 account_id：
Web session 用会话账户，loopback owner-console 用账本 owner 账户。

**纯只读**：记账/还款/调整/作废/成员还款确认全部留 Android + ``/api``。成员代理还款收发箱
状态 + 「过往」历史是 slice 2b。文案逐字镜像 Android ``MemberDebtLabels`` + ``strings_stats_budget.xml``
(§14 三端 copy 同步)。
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
from app.services.debt_service import get_participant_debt_response, list_debts
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


def _debt_view(debt) -> dict:
    """列表行视图模型 (slice 1)。"""
    name = (debt.counterparty_label or "").strip() or _COUNTERPARTY_FALLBACK.get(
        debt.counterparty_type, _COUNTERPARTY_FALLBACK["external"]
    )
    return {
        "public_id": debt.public_id,
        "name": name,
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
    listing = list_debts(db, tenant_id=selected_id)
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠款",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["debts"] = [_debt_view(debt) for debt in listing.items]
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
    ctx["debt"] = _detail_view(debt)
    return templates.TemplateResponse(request=request, name="debt_detail.html", context=ctx)

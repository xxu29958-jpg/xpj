"""/web 桌面账本 · 欠我的 (应收) (ADR-0049 债务域 web 面 ⑤c-3 / P3b creditor 发现 + W2-C 合并 lens).

只读列出**别人还没还你的**——viewer-personal 应收的 canonical lens
(``list_receivables_for_account``)：同账本 external/member 应收 + 跨账本 member 应收
(bill_split 成员债住在**债务人的账本**,发起人在自己账本欠款页看不到,跨账本部分补上),
去重合并。account-scoped,跨该账户所有账本。

行形两轴(与 ``/web/debts`` 同一套词汇,行形判定复用 ``_is_member_view`` 含 FX 防御):
member 行 = communal 关系行(债务人名 + 关系主句「我帮你垫的…」+ open 时细进度条 +
状态徽章 neutral/success **永不红**);external 行 = 会计行(方向徽章「应收」+ 会计状态词
+ 剩余/本金,作废 danger — 镜像 debtLinkStatusTone,不受 member 红线约束)。每行保留
canonical remaining 与 public_id,打开既有 participant-scoped detail;写动作仍由真实角色
与 Owner 决定,不催、不汇总记分。

viewer 由 ``_web_viewer_account_id`` 解析(web session→会话账户;loopback owner-console
→选定账本 owner,同 slice 2a/2b/3/4);viewer None(账本无活跃 owner)→ premium 空态。
跨账本 member 行的 ``ledger_id`` 已被服务端 redact 成 None(§5.2/ADR-0029,债权人不得知
债务人挂哪个账本);同账本行保留 ``ledger_id``。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.routes.web_debts import (
    _MEMBER_STATUS,
    _STATUS_LABELS,
    _STATUS_RANK,
    _STATUS_TONE,
    _communal_ratio,
    _debt_name,
    _home_amount_label,
    _is_member_view,
    _member_headline,
    _member_progress_note,
    _web_viewer_account_id,
)
from app.services.debt_service import list_receivables_for_account

router = APIRouter(prefix="/web/receivables", tags=["web"])

_INTRO = "别人还欠你的外借、垫付和已接受拆账份额都在这里。点开一笔查看并处理还款。"
_EMPTY_TITLE = "还没有欠你的款"
_EMPTY_BODY = "当前账本和跨账本拆账里，还没有记录到欠你的款项。"


def _receivable_row_view(debt) -> dict:
    """一行应收的视图 (W2-C 合并 lens：同账本 external/member + 跨账本 member)。

    member 行 (viewer 恒是债权人 ``viewer_is_debtor=False``) = communal 关系行：债务人名 +
    关系主句「我帮你垫的…」+ open 时细进度条 + 状态徽章 (neutral/success **永不红**)。
    external 行 = 会计行：方向徽章「应收」+ 会计状态词 (作废 danger，镜像 debtLinkStatusTone；
    member 永不红红线只管 communal 行) + 剩余/本金脚注。会计分支覆盖两路来货：viewer 自己
    的 owner-relative ``owed_to_me`` 外借 (``viewer_is_debtor=None``)，以及被 FX 防御退回的
    外币 member 债 (``direction`` 是 owner-relative「i_owe」)——本 endpoint 已保证 viewer 是
    债权人，故徽章按 viewer-relative ``viewer_is_debtor`` 判定，不照搬 owner-relative
    ``direction`` (那会把 viewer 的应收翻成「应付」)。行形判定复用 ``_is_member_view`` (含
    FX 防御)，与 ``/web/debts`` 列表↔详情同轴。无金额英雄 (§7.0 命名不催)，只安静显示
    exact remaining 并进入既有 participant detail。"""
    view: dict = {
        "public_id": debt.public_id,
        # name = member 行债务人 display_name / external 行自由文本 label，回退见 _debt_name。
        "name": _debt_name(debt),
        # 已结清/作废行视觉沉降(淡出 — 办完可追溯)。
        "recede": debt.status != "open",
        "remaining_label": _home_amount_label(
            debt.remaining_amount_cents,
            debt.home_currency_code,
        ),
    }
    if _is_member_view(debt):
        ratio = _communal_ratio(debt.paid_amount_cents, debt.principal_amount_cents)
        member_status_label, member_status_tone = _MEMBER_STATUS.get(debt.status, _MEMBER_STATUS["open"])
        view.update(
            {
                "is_member": True,
                "member_headline": _member_headline(
                    debt.viewer_is_debtor, debt.status, debt.is_forgiven, ratio
                ),
                "show_progress": debt.status == "open",
                "ratio_percent": int(round(ratio * 100)),
                "progress_note": _member_progress_note(ratio),
                "status_label": member_status_label,
                "status_tone": member_status_tone,
                "direction_label": None,
                "principal_label": None,
            }
        )
    else:
        view.update(
            {
                "is_member": False,
                "member_headline": None,
                "show_progress": False,
                "ratio_percent": 0,
                "progress_note": None,
                # 方向徽章 viewer-relative：本 endpoint 已保证 viewer 是债权人 (含 FX
                # 防御退回的外币 member 债——其 direction 是 owner-relative「i_owe」)，
                # 不得照搬 owner-relative ``debt.direction`` (service docstring 同诫)。
                "direction_label": "应付" if debt.viewer_is_debtor else "应收",
                "principal_label": _home_amount_label(
                    debt.principal_amount_cents,
                    debt.home_currency_code,
                ),
                "status_label": _STATUS_LABELS.get(debt.status, "未结清"),
                "status_tone": _STATUS_TONE.get(debt.status, ""),
            }
        )
    return view


@router.get("", response_class=HTMLResponse)
def web_receivables(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    # selected ledger drives the shell/sidebar AND resolves the loopback viewer account;
    # the receivables list itself is account-scoped (cross-ledger), not ledger-scoped.
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _web_viewer_account_id(request, db, selected_id)
    rows = (
        list_receivables_for_account(db, tenant_id=selected_id, account_id=account_id).items
        if account_id is not None
        else []
    )
    # Active-first: open receivables before cleared/voided (sunk to the bottom). The
    # service returns status.asc (alphabetical → cleared before open), so re-sort here —
    # mirroring web_debts._split_debt_views + Android sortReceivablesActiveFirst (shared 1A
    # _STATUS_RANK). Python's stable sort preserves the service's created_at order in-rank.
    rows = sorted(rows, key=lambda d: _STATUS_RANK.get(d.status, 0))
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="欠我的",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["intro"] = _INTRO
    ctx["rows"] = [_receivable_row_view(debt) for debt in rows]
    ctx["empty_title"] = _EMPTY_TITLE
    ctx["empty_body"] = _EMPTY_BODY
    return templates.TemplateResponse(request=request, name="receivables.html", context=ctx)

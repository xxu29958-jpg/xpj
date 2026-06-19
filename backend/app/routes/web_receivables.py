"""/web 桌面账本 · 欠我的 (应收) (ADR-0049 债务域 web 面 ⑤c-3 / P3b creditor 发现).

只读列出**别人还没和你对上的份额**——你作为跨账本 member 债权人的应收。``list_debts``
是 ledger-scoped,bill_split 成员债住在**债务人的账本**(owner=债务人、counterparty=
发起人=债权人),所以发起人在自己账本的欠款页看不到这些应收;这一页补上(``GET
/web/receivables``,**account-scoped 非 ledger-scoped**,跨该账户所有账本)。

每行走 communal 关系行(逐字复用 ``web_debts`` 的成员行词汇,三端同一套呈现):债务人名
(``counterparty_label`` 由 ⑤c-1 填成 debtor 的 display_name)+ 关系主句「我帮你垫的…」
(viewer 恒是债权人 → ``viewer_is_debtor=False``)+ open 时细进度条 + 状态徽章
(neutral/success **永不红**)。**纯只读、非链接**(镜像还款捕获审计页):还款由债务人在
手机 App 发起、债权人确认;§7.0 命名要对上的人但不催、不红、不汇总记分。

viewer 由 ``_web_viewer_account_id`` 解析(web session→会话账户;loopback owner-console
→选定账本 owner,同 slice 2a/2b/3/4);viewer None(账本无活跃 owner)→ premium 空态。
``ledger_id`` 已被服务端 redact 成 None(§5.2/ADR-0029,债权人不得知债务人挂哪个账本)。
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
    _communal_ratio,
    _debt_name,
    _member_headline,
    _member_progress_note,
    _web_viewer_account_id,
)
from app.services.debt_service import list_member_receivables_for_account

router = APIRouter(prefix="/web/receivables", tags=["web"])

_INTRO = "家人接受你发起的拆账后,还没和你对上的份额都在这里(跨账本汇总)。还款请在手机 App 由对方发起、你确认。"
_EMPTY_TITLE = "还没有待对上的款"
_EMPTY_BODY = "你帮家人垫了钱、对方接受拆账后,还没对上的份额会显示在这里。"


def _receivable_row_view(debt) -> dict:
    """一行应收的 communal 关系行视图。viewer 恒是债权人(``viewer_is_debtor=False``,由
    ``list_member_receivables_for_account`` 的查询保证),故关系主句恒走「我帮你垫的…」侧,
    与 ``/web/debts`` 家人段同一套词汇。无金额英雄(§7.0 命名不催),金额只隐含在进度条。"""
    ratio = _communal_ratio(debt.paid_amount_cents, debt.principal_amount_cents)
    status_label, status_tone = _MEMBER_STATUS.get(debt.status, _MEMBER_STATUS["open"])
    return {
        # name = 债务人 display_name(⑤c-1 把它填进 counterparty_label),回退「家庭成员」。
        "name": _debt_name(debt),
        "member_headline": _member_headline(
            debt.viewer_is_debtor, debt.status, debt.is_forgiven, ratio
        ),
        "show_progress": debt.status == "open",
        "ratio_percent": int(round(ratio * 100)),
        "progress_note": _member_progress_note(ratio),
        "status_label": status_label,
        "status_tone": status_tone,
        # 已结清/作废行视觉沉降(淡出、永不红 — 办完可追溯)。
        "recede": debt.status != "open",
    }


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
        list_member_receivables_for_account(db, account_id=account_id).items
        if account_id is not None
        else []
    )
    ctx = _base_ctx(
        request,
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

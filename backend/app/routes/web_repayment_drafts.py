"""/web 桌面账本 · 还款捕获审计 (ADR-0049 债务域 web 面 slice 3).

只读**审计日志**:Android NotificationListenerService 自动捕获的还款通知 (花呗/借呗/白条/
京东/美团月付/银行卡) 在这里留一份只读记录。**actionable 全留 Android + /api**:选债/确认/
忽略不在 web 做 (顶部「只读审计:复核与确认请在手机 App」)。

**account-scoped 非 ledger-scoped**(隐私边界):还款捕获是**个人的**(你手机的支付通知),
ledger-scoped 会把所有成员的私人捕获暴露给任何看该账本的人;这里只列 **viewer 自己创建的**
捕获 (``created_by_account_id == viewer``),跨该账户所有账本、新近排序。viewer 由
``_web_viewer_account_id`` 解析 (web session→会话账户;loopback owner-console=管理端→选定账本
owner 账户,同 slice 2a/2b/4);viewer None (账本无活跃 owner) → premium 空态。

每行:来源 (渠道名) · 商户 · 额 · 捕获日 · 状态 pill。pending → ``待复核`` neutral +
**描述性 provenance**「系统猜测对应:<对手方>」(服务端 ephemeral 建议债,可能过期,非预选
actionable);confirmed → ``已记账`` + 关联债名;dismissed → ``已忽略`` 沉降。建议债/关联债名
由服务端解析 (审计跨账本,Debt 读留服务层 §1),route 只套用 prefix + 外部欠款 fallback。
"""

from __future__ import annotations

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
from app.routes.web_debts import _COUNTERPARTY_FALLBACK, _day_label, _web_viewer_account_id
from app.services.debt_service import (
    RepaymentDraftAuditRow,
    list_repayment_draft_audit_for_account,
)
from app.services.debt_service._repayment_draft import REPAYMENT_DRAFT_SOURCE_LABELS

router = APIRouter(prefix="/web/repayment-drafts", tags=["web"])

# 顶部只读提示 + 空态 (premium，复用 .dt-card--empty)。
_AUDIT_INTRO = "只读审计:复核与确认请在手机 App。"
_EMPTY_TITLE = "还没有还款捕获"
_EMPTY_BODY = "手机 App 自动捕获的还款通知会在这里留一份只读记录;复核与确认请在手机 App。"

# 状态标签 + 色调 (pending 中性 / confirmed 成功 / dismissed 弱化沉降，永不 danger)。
_STATUS_LABELS = {"pending": "待复核", "confirmed": "已记账", "dismissed": "已忽略"}
_STATUS_TONE = {"pending": "", "confirmed": "ok", "dismissed": "muted"}
# 建议债 / 关联债 描述性前缀 (pending=ephemeral 猜测，非预选；confirmed=已记到的债)。
_SUGGESTION_PREFIX = "系统猜测对应:{}"
_LINKED_PREFIX = "已记到:{}"


def _audit_row_view(row: RepaymentDraftAuditRow) -> dict:
    """一行审计记录的渲染视图。建议债/关联债恒是**外部/manual** 债 (matcher 候选 + confirm
    guard 均 external-only,且外部债建账强制非空 counterparty_label),故名恒存在;`外部欠款`
    fallback 是防御性的——保证永不渲染「已记到:None」(镜像 web_debts `_debt_name` 的回退模式)。"""
    view: dict = {
        "source_label": REPAYMENT_DRAFT_SOURCE_LABELS.get(row.source, row.source),
        "merchant": (row.merchant_label or "").strip() or None,
        "amount_label": _home_amount_label(row.amount_cents, row.home_currency_code),
        "captured_label": _day_label(row.captured_at),
        "status_label": _STATUS_LABELS.get(row.status, _STATUS_LABELS["pending"]),
        "status_tone": _STATUS_TONE.get(row.status, ""),
        "recede": row.status == "dismissed",
    }
    if row.status == "confirmed":
        name = row.linked_debt_label or _COUNTERPARTY_FALLBACK["external"]
        view["linked_line"] = _LINKED_PREFIX.format(name)
    elif row.status == "pending" and row.has_suggestion:
        name = row.suggested_debt_label or _COUNTERPARTY_FALLBACK["external"]
        view["provenance"] = _SUGGESTION_PREFIX.format(name)
    return view


@router.get("", response_class=HTMLResponse)
def web_repayment_drafts(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    # selected ledger drives the shell/sidebar AND resolves the loopback viewer account;
    # the draft list itself is account-scoped (viewer's own captures), not ledger-scoped.
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    account_id = _web_viewer_account_id(request, db, selected_id)
    rows = (
        list_repayment_draft_audit_for_account(db, account_id=account_id)
        if account_id is not None
        else []
    )
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="还款捕获",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["intro"] = _AUDIT_INTRO
    ctx["rows"] = [_audit_row_view(row) for row in rows]
    ctx["empty_title"] = _EMPTY_TITLE
    ctx["empty_body"] = _EMPTY_BODY
    return templates.TemplateResponse(request=request, name="repayment_drafts.html", context=ctx)

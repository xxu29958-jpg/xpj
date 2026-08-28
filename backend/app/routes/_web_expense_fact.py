"""Read-first fact detail + human timeline view-models for confirmed expenses.

confirmed 账单的 /web 落地页不再是编辑表单（见 web_expense_edit.web_edit_get
的状态分支）：本模块把``GET /api/expenses/{id}/revisions`` 的服务端快照
翻译成「人话时间线」——只有用户可写字段产出 before→after delta，系统字段
（汇率快照/fx_status/items_sum_status 等）降层级折叠，revision_number、
row_version、actor id 永不渲染（RR-1 视觉裁决：系统细节不进主文案）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_helpers import web_edit_context
from app.routes._web_money_views import _minor_amount_label
from app.routes.web_bill_split import build_split_invite_context
from app.routes.web_common import _web_redirect, templates
from app.services.expense_revision_service import list_expense_revisions
from app.services.expense_service import get_expense
from app.services.spending_contract_service import accounting_datetime_label

# 用户可写字段 → 时间线人话标签。对照 expense_revision_service._SCALAR_FIELDS；
# 未列出的快照字段（home_currency_code / exchange_rate_* / fx_status / source /
# confirmed_at / items_sum_status）视为系统细节，不进 delta 列表。
_FACT_FIELD_LABELS: dict[str, str] = {
    "amount_cents": "入账金额",
    "original_currency_code": "原币币种",
    "original_amount_minor": "原币金额",
    "merchant": "商家",
    "category": "分类",
    "note": "备注",
    "tags": "标签",
    "expense_time": "消费时间",
    "value_score": "值回票价",
    "regret_score": "后悔指数",
    "items": "小票明细",
    "splits": "家庭拆账",
}

# changed_fields 顺序稳定化：金额最先，明细/拆账最后。
_FACT_FIELD_ORDER = tuple(_FACT_FIELD_LABELS)

_KIND_LABELS = {"confirmed": "首次确认", "correction": "更正"}


def _snapshot_time_label(value: object) -> str:
    """Snapshots carry ISO strings (expense_revision_service._json_value)."""

    if not value:
        return "（空）"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return accounting_datetime_label(parsed) or text


def _format_fact_value(
    field: str,
    value: object,
    snapshot: dict[str, object],
    home_currency_code: str,
) -> str:
    if value is None or value == "":
        return "（空）"
    if field == "amount_cents":
        return _minor_amount_label(value if isinstance(value, int) else None, home_currency_code)
    if field == "original_amount_minor":
        original_code = str(snapshot.get("original_currency_code") or home_currency_code)
        return _minor_amount_label(value if isinstance(value, int) else None, original_code)
    if field == "expense_time":
        return _snapshot_time_label(value)
    if field in {"items", "splits"} and isinstance(value, list):
        return f"共 {len(value)} 行"
    return str(value)


def _timeline_changes(
    revision: dict[str, Any],
    home_currency_code: str,
) -> list[dict[str, str]]:
    """Translate changed_fields into before→after deltas for user-writable fields."""

    changed_fields = revision.get("changed_fields") or []
    if revision.get("change_kind") != "correction":
        return []
    before = revision.get("before") or {}
    after = revision.get("after") or {}
    changes: list[dict[str, str]] = []
    ordered = [f for f in _FACT_FIELD_ORDER if f in changed_fields]
    for field in ordered:
        changes.append(
            {
                "label": _FACT_FIELD_LABELS[field],
                "before": _format_fact_value(field, before.get(field), before, home_currency_code),
                "after": _format_fact_value(field, after.get(field), after, home_currency_code),
            }
        )
    if not changes:
        # 更正实际只触到系统字段（理论上少见）：一句话折叠，不渲染字段名。
        changes.append({"label": "系统信息", "before": "", "after": "已更新"})
    return changes


def build_fact_timeline(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    home_currency_code: str,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    """Newest-first human timeline rows for the fact page."""

    response = list_expense_revisions(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        page=1,
        page_size=page_size,
    )
    rows: list[dict[str, Any]] = []
    for item in response.items:
        revision = item.model_dump()
        actor_parts = [part for part in (item.actor_account_name, item.actor_device_name) if part]
        rows.append(
            {
                "revision_number": item.revision_number,
                "kind": item.change_kind,
                "kind_label": _KIND_LABELS.get(item.change_kind, item.change_kind),
                "reason": item.reason,
                "when": _snapshot_time_label(item.created_at.isoformat()),
                "actor": " · ".join(actor_parts),
                "is_correction": item.change_kind == "correction",
                "changes": _timeline_changes(revision, home_currency_code),
            }
        )
    return rows


def web_fact_context(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    *,
    message: str | None = None,
    error: str | None = None,
) -> dict:
    """Read-first fact page context: base edit view-model + fact extras."""

    ctx = web_edit_context(db, request, options, selected_id, expense_id)
    expense = get_expense(db, expense_id, selected_id)
    # 页级装配事实（A1 复裁）：事实页是三级详情工作区，依赖 detail.css 的
    # .detail-layout/.receipt-preview。正常 GET /edit 时 base.html 的 URL 子串
    # 判定也能得出 tertiary，但 confirmed 旧命令失权后的 409 重渲（POST
    # /save|items/save|splits/save|reject）path 不含 /edit —— 页面所需样式必须
    # 由显式 context 事实决定，不能靠 URL 猜测；base.html 优先消费本标记。
    ctx["page_surface"] = "tertiary"
    ctx["expense"]["fact_revision"] = getattr(expense, "fact_revision", 0)
    ctx["expense"]["confirmed_at_label"] = (
        accounting_datetime_label(expense.confirmed_at) if expense.confirmed_at else ""
    )
    ctx["page_title"] = "账单详情"
    ctx["message"] = message if message is not None else request.query_params.get("msg")
    ctx["error"] = error
    ctx["split_invite"] = build_split_invite_context(
        db,
        request,
        selected_ledger_id=selected_id,
        expense=ctx["expense"],
        can_write=ctx["can_write"],
    )
    ctx["fact_timeline"] = build_fact_timeline(
        db,
        tenant_id=selected_id,
        expense_id=expense_id,
        home_currency_code=ctx["home_currency_code"],
    )
    return ctx


def web_fact_error_response(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    message: str,
    *,
    status_code: int = 409,
) -> Response:
    """confirmed 命中已失权的旧 Web 命令（save/items/splits/reject）时的诚实
    呈现：事实页 + 错误条 + 明确 409 —— 不用成功重定向掩盖（A1 检查点合同 5）。
    行已消失（跨端删除）时退化为列表页 flash 重定向。"""

    try:
        ctx = web_fact_context(
            db,
            request,
            options,
            selected_id,
            expense_id,
            error=message,
        )
    except AppError as exc:
        return _web_redirect(
            "/web/confirmed",
            selected_id,
            msg=exc.message,
            flash_type="error",
        )
    return templates.TemplateResponse(
        request=request,
        name="expense_fact.html",
        context=ctx,
        status_code=status_code,
    )

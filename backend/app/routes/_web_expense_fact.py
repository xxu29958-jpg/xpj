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
from uuid import uuid4

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_expense_fact_pager import fact_timeline_page_context
from app.routes._web_expense_helpers import web_edit_context
from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    clean_return_to,
    flow_href,
    return_href,
    return_label,
)
from app.routes._web_money_views import _minor_amount_label
from app.routes.web_bill_split import build_split_invite_context
from app.routes.web_common import _web_redirect, templates
from app.services import invitation_members
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
_FACT_FLASH_TYPES = frozenset({"success", "error", "warning"})


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


def _snapshot_allocation_label(
    snapshot: dict[str, object],
    home_currency_code: str,
) -> str | None:
    splits = snapshot.get("splits")
    amount_cents = snapshot.get("amount_cents")
    if not isinstance(splits, list) or not splits or not isinstance(amount_cents, int):
        return None
    amounts = [row.get("amount_cents") for row in splits if isinstance(row, dict)]
    if len(amounts) != len(splits) or any(not isinstance(value, int) for value in amounts):
        return None
    remaining = amount_cents - sum(amounts)
    if remaining == 0:
        return "已分完"
    amount_label = _minor_amount_label(abs(remaining), home_currency_code)
    return f"还差 {amount_label} 未分配" if remaining > 0 else f"已拆超出 {amount_label}"


def _item_snapshot_rows(
    value: object,
    home_currency_code: str,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for raw_row in value:
        if not isinstance(raw_row, dict):
            continue
        title = str(raw_row.get("name") or "").strip() or "未命名明细"
        facts: list[str] = []
        quantity = str(raw_row.get("quantity_text") or "").strip()
        if quantity:
            facts.append(quantity)
        unit_price = raw_row.get("unit_price_cents")
        if isinstance(unit_price, int):
            facts.append(f"单价 {_minor_amount_label(unit_price, home_currency_code)}")
        amount = raw_row.get("amount_cents")
        if isinstance(amount, int):
            facts.append(f"金额 {_minor_amount_label(amount, home_currency_code)}")
        category = str(raw_row.get("category") or "").strip()
        if category:
            facts.append(category)
        rows.append({"title": title, "facts": facts})
    return rows


def _split_snapshot_rows(
    value: object,
    home_currency_code: str,
    member_names: dict[int, str],
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for raw_row in value:
        if not isinstance(raw_row, dict):
            continue
        member_id = raw_row.get("member_id")
        title = member_names.get(member_id, "") if isinstance(member_id, int) else ""
        facts: list[str] = []
        amount = raw_row.get("amount_cents")
        if isinstance(amount, int):
            facts.append(_minor_amount_label(amount, home_currency_code))
        note = str(raw_row.get("note") or "").strip()
        if note:
            facts.append(note)
        rows.append({"title": title or "已移除的成员", "facts": facts})
    return rows


def _collection_details(
    *,
    field: str,
    before: dict[str, object],
    after: dict[str, object],
    home_currency_code: str,
    member_names: dict[int, str],
) -> dict[str, list[dict[str, object]]]:
    if field == "items":
        return {
            "before_rows": _item_snapshot_rows(before.get(field), home_currency_code),
            "after_rows": _item_snapshot_rows(after.get(field), home_currency_code),
        }
    return {
        "before_rows": _split_snapshot_rows(before.get(field), home_currency_code, member_names),
        "after_rows": _split_snapshot_rows(after.get(field), home_currency_code, member_names),
    }


def _split_timeline_changes(
    *,
    before: dict[str, object],
    after: dict[str, object],
    home_currency_code: str,
    member_names: dict[int, str],
) -> list[dict[str, Any]]:
    before_count = _format_fact_value("splits", before.get("splits"), before, home_currency_code)
    after_count = _format_fact_value("splits", after.get("splits"), after, home_currency_code)
    before_allocation = _snapshot_allocation_label(before, home_currency_code)
    after_allocation = _snapshot_allocation_label(after, home_currency_code)
    allocation_changed = (
        before_allocation is not None and after_allocation is not None and before_allocation != after_allocation
    )
    changes: list[dict[str, Any]] = []
    if allocation_changed:
        changes.append(
            {
                "label": _FACT_FIELD_LABELS["splits"],
                "before": before_allocation,
                "after": after_allocation,
            }
        )
    if before_count != after_count or not allocation_changed:
        changes.append(
            {
                "label": _FACT_FIELD_LABELS["splits"],
                "before": before_count,
                "after": after_count,
            }
        )
    changes[-1]["details"] = _collection_details(
        field="splits",
        before=before,
        after=after,
        home_currency_code=home_currency_code,
        member_names=member_names,
    )
    return changes


def _timeline_changes(
    revision: dict[str, Any],
    home_currency_code: str,
    *,
    member_names: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Translate changed_fields into before→after deltas for user-writable fields."""

    changed_fields = revision.get("changed_fields") or []
    if revision.get("change_kind") != "correction":
        return []
    before = revision.get("before") or {}
    after = revision.get("after") or {}
    resolved_member_names = member_names or {}
    changes: list[dict[str, Any]] = []
    ordered = [f for f in _FACT_FIELD_ORDER if f in changed_fields]
    for field in ordered:
        if field == "splits":
            changes.extend(
                _split_timeline_changes(
                    before=before,
                    after=after,
                    home_currency_code=home_currency_code,
                    member_names=resolved_member_names,
                )
            )
            continue
        change: dict[str, Any] = {
            "label": _FACT_FIELD_LABELS[field],
            "before": _format_fact_value(field, before.get(field), before, home_currency_code),
            "after": _format_fact_value(field, after.get(field), after, home_currency_code),
        }
        if field == "items":
            change["details"] = _collection_details(
                field=field,
                before=before,
                after=after,
                home_currency_code=home_currency_code,
                member_names=resolved_member_names,
            )
        changes.append(change)
        if field == "amount_cents" and "splits" not in changed_fields:
            before_allocation = _snapshot_allocation_label(before, home_currency_code)
            after_allocation = _snapshot_allocation_label(after, home_currency_code)
            if before_allocation and after_allocation and before_allocation != after_allocation:
                changes.append(
                    {
                        "label": _FACT_FIELD_LABELS["splits"],
                        "before": before_allocation,
                        "after": after_allocation,
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
    current_revision: int,
    snapshot_revision: int | None = None,
    page: int = 1,
    page_size: int = 50,
    member_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Newest-first human timeline rows for the fact page."""

    response = list_expense_revisions(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        current_revision=current_revision,
        snapshot_revision=snapshot_revision,
        page=page,
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
                "changes": _timeline_changes(
                    revision,
                    home_currency_code,
                    member_names=member_names,
                ),
            }
        )
    return {
        "entries": rows,
        "page": response.page,
        "page_size": response.page_size,
        "total": response.total,
        "snapshot_revision": response.snapshot_revision,
        "has_newer": response.page > 1,
        "has_older": response.page * response.page_size < response.total,
    }


def web_fact_context(
    db: Session,
    request: Request,
    options,
    selected_id: str,
    expense_id: int,
    *,
    revision_page: int = 1,
    revision_snapshot: int | None = None,
    message: str | None = None,
    flash_type: str = "",
    error: str | None = None,
    return_context: ExpenseReturnContext = ExpenseReturnContext(),
) -> dict:
    """Read-first fact page context: base edit view-model + fact extras."""

    return_values = return_context.as_kwargs()
    ctx = web_edit_context(db, request, options, selected_id, expense_id, **return_values)
    if not clean_return_to(return_context.return_to):
        ctx["edit_return_href"] = return_href(
            "",
            ledger_id=selected_id,
            default_path="/web/confirmed",
        )
        ctx["edit_return_label"] = return_label("confirmed")
    ctx["correction_href"] = flow_href(
        f"/web/expenses/{expense_id}/correct",
        ledger_id=selected_id,
        **return_values,
    )
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
    ctx["items_ack_idempotency_key"] = str(uuid4())
    ctx["message"] = message if message is not None else request.query_params.get("msg")
    ctx["flash_type"] = flash_type if flash_type in _FACT_FLASH_TYPES else ""
    ctx["error"] = error
    ctx["split_invite"] = build_split_invite_context(
        db,
        request,
        selected_ledger_id=selected_id,
        expense=ctx["expense"],
        can_write=ctx["can_write"],
    )
    member_names = {
        member.member_id: member.account_name
        for member in invitation_members.list_members(
            db,
            ledger_id=selected_id,
            requester_account_id=0,
        )
    }
    timeline = build_fact_timeline(
        db,
        tenant_id=selected_id,
        expense_id=expense_id,
        home_currency_code=ctx["home_currency_code"],
        current_revision=expense.fact_revision,
        snapshot_revision=revision_snapshot,
        page=revision_page,
        member_names=member_names,
    )
    ctx["fact_timeline"] = timeline["entries"]
    ctx["fact_timeline_page"] = fact_timeline_page_context(
        request,
        timeline=timeline,
        expense_id=expense_id,
        selected_ledger_id=selected_id,
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

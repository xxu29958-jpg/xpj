"""Backend-owned read projection for the Desktop five-domain workbench."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE
from app.schemas._desktop_product import (
    DesktopInboxEdit,
    DesktopProductLedger,
    DesktopProductRow,
    DesktopWorkspaceKey,
    DesktopWorkspaceResponse,
)
from app.services._desktop_product_labels import (
    _STATUS_LABELS,
    _debt_kind_label,
    _debt_role_label,
    _field,
    _iso,
    _money,
    _temporal_precision,
)
from app.services._desktop_product_planning import insights_rows, plan_rows
from app.services.currency_common import (
    currency_symbol,
    home_currency_code,
    minor_unit_digits,
)
from app.services.debt_service import (
    list_payables_for_account,
    list_receivables_for_account,
)
from app.services.expense_service import list_confirmed, list_pending
from app.services.time_service import now_utc

if TYPE_CHECKING:
    from app.models import Expense

_ROW_LIMIT = 200
_WORKSPACE_TITLES: dict[DesktopWorkspaceKey, str] = {
    "inbox": "收件",
    "transactions": "流水",
    "obligations": "往来",
    "plans": "计划",
    "insights": "洞察",
}
_EMPTY_COPY: dict[DesktopWorkspaceKey, tuple[str, str]] = {
    "inbox": ("收件箱已清空", "当前没有等待复核的票据。"),
    "transactions": ("还没有已确认流水", "确认后的票据会出现在这里。"),
    "obligations": ("当前没有往来事项", "欠款和应收事实出现后会列在这里。"),
    "plans": ("当前没有计划条目", "预算尚未配置，且没有目标、收入或固定支出。"),
    "insights": ("暂无可展示洞察", "账本产生流水后再刷新查看。"),
}


def _expense_row(expense: Expense, *, workspace: DesktopWorkspaceKey) -> DesktopProductRow:
    status = "pending" if workspace == "inbox" else "confirmed"
    home_currency = (expense.home_currency_code or DEFAULT_HOME_CURRENCY_CODE).upper()
    original_currency = (expense.original_currency_code or home_currency).upper()
    original_amount = (
        expense.original_amount_minor
        if expense.original_amount_minor is not None
        else expense.amount_cents
    )
    image_state = (
        "可查看"
        if expense.image_path and expense.image_deleted_at is None
        else ("已按策略清理" if expense.image_deleted_at is not None else "无图片")
    )
    flags: list[str] = []
    if expense.amount_cents is None:
        flags.append("缺金额")
    if not (expense.merchant or "").strip():
        flags.append("缺商家")
    if expense.duplicate_status == "suspected":
        flags.append("疑似重复")
    subtitle_parts = [expense.category or "未分类", expense.source or "未知来源", *flags]
    occurred_at = expense.expense_time or expense.confirmed_at or expense.created_at
    return DesktopProductRow(
        key=f"expense:{expense.public_id}",
        kind="expense",
        title=(expense.merchant or "").strip() or "待补商家",
        subtitle=" · ".join(part for part in subtitle_parts if part),
        status=status,
        status_label=_STATUS_LABELS[status],
        amount_minor=expense.amount_cents,
        currency_code=home_currency,
        occurred_at=_iso(occurred_at),
        occurred_precision=_temporal_precision(occurred_at),
        fields=[
            _field("分类", expense.category, "未分类"),
            _field("来源", expense.source, "未知"),
            _field("消费时间", _iso(expense.expense_time)),
            _field("备注", expense.note),
            _field("标签", expense.tags),
            _field("图片", image_state),
        ],
        capabilities=["save", "confirm", "ignore"] if workspace == "inbox" else [],
        edit=(
            DesktopInboxEdit(
                expected_row_version=expense.row_version,
                amount_minor=original_amount,
                currency_code=original_currency,
                currency_symbol=currency_symbol(original_currency),
                minor_unit_digits=minor_unit_digits(original_currency),
                home_amount_minor=expense.amount_cents,
                home_currency_code=home_currency,
                original_amount_minor=original_amount,
                original_currency_code=original_currency,
                exchange_rate_to_home=expense.exchange_rate_to_cny,
                exchange_rate_date=expense.exchange_rate_date,
                exchange_rate_source=expense.exchange_rate_source,
                fx_status=expense.fx_status,
                merchant=(expense.merchant or "").strip(),
                category=expense.category or "未分类",
            )
            if workspace == "inbox"
            else None
        ),
    )


def _inbox_rows(db: Session, ledger_id: str) -> tuple[list[DesktopProductRow], int]:
    expenses = list_pending(db, ledger_id)
    return ([_expense_row(item, workspace="inbox") for item in expenses[:_ROW_LIMIT]], len(expenses))


def _transaction_rows(db: Session, ledger_id: str) -> tuple[list[DesktopProductRow], int]:
    expenses, total = list_confirmed(
        db,
        tenant_id=ledger_id,
        page=1,
        page_size=_ROW_LIMIT,
    )
    return ([_expense_row(item, workspace="transactions") for item in expenses], total)


def _personal_obligations(
    db: Session,
    *,
    ledger_id: str,
    account_id: int,
) -> list[Any]:
    payables = list_payables_for_account(
        db,
        tenant_id=ledger_id,
        account_id=account_id,
    ).items
    receivables = list_receivables_for_account(
        db,
        tenant_id=ledger_id,
        account_id=account_id,
    ).items
    rows: list[Any] = []
    seen: set[str] = set()
    for debt, viewer_is_debtor in [
        *((item, True) for item in payables),
        *((item, False) for item in receivables),
    ]:
        if debt.public_id in seen:
            continue
        seen.add(debt.public_id)
        rows.append(debt.model_copy(update={"viewer_is_debtor": viewer_is_debtor}))
    return rows


def _obligation_rows(
    db: Session,
    ledger_id: str,
    *,
    account_id: int,
) -> tuple[list[DesktopProductRow], int]:
    debts = _personal_obligations(
        db,
        ledger_id=ledger_id,
        account_id=account_id,
    )
    rows = [
        DesktopProductRow(
            key=f"debt:{debt.public_id}",
            kind="debt",
            title=(debt.counterparty_label or "").strip() or "未命名往来对象",
            subtitle=_debt_role_label(
                debt.counterparty_type,
                debt.viewer_is_debtor,
            ),
            status=debt.status,
            status_label=_STATUS_LABELS.get(debt.status, debt.status),
            amount_minor=debt.remaining_amount_cents,
            currency_code=debt.home_currency_code,
            occurred_at=_iso(debt.updated_at),
            occurred_precision=_temporal_precision(debt.updated_at),
            fields=[
                _field("往来类型", "家庭成员" if debt.counterparty_type == "member" else "外部往来"),
                _field("原始金额", _money(debt.principal_amount_cents, debt.home_currency_code)),
                _field("已清算", _money(debt.paid_amount_cents, debt.home_currency_code)),
                _field("待清算", _money(debt.remaining_amount_cents, debt.home_currency_code)),
                _field("还款类型", _debt_kind_label(debt.debt_kind)),
            ],
        )
        for debt in debts[:_ROW_LIMIT]
    ]
    return rows, len(debts)


def build_desktop_workspace(
    db: Session,
    *,
    workspace: DesktopWorkspaceKey,
    account_id: int,
    ledger_id: str,
    ledger_name: str,
    role: str,
    ledgers: list[DesktopProductLedger],
) -> DesktopWorkspaceResponse:
    configured_currency = home_currency_code()
    if workspace == "obligations":
        rows, total_count = _obligation_rows(
            db,
            ledger_id,
            account_id=account_id,
        )
    elif workspace == "plans":
        rows, total_count = plan_rows(
            db,
            ledger_id,
            currency_code=configured_currency,
        )
    elif workspace == "insights":
        rows, total_count = insights_rows(
            db,
            ledger_id,
            currency_code=configured_currency,
        )
    else:
        builders = {
            "inbox": _inbox_rows,
            "transactions": _transaction_rows,
        }
        rows, total_count = builders[workspace](db, ledger_id)
    if workspace == "inbox" and role not in {"owner", "member"}:
        for row in rows:
            row.capabilities = []
    empty_title, empty_detail = _EMPTY_COPY[workspace]
    return DesktopWorkspaceResponse(
        workspace=workspace,
        title=_WORKSPACE_TITLES[workspace],
        ledger_id=ledger_id,
        ledger_name=ledger_name,
        role=role,
        generated_at=now_utc(),
        rows=rows,
        total_count=total_count,
        truncated=total_count > len(rows),
        empty_title=empty_title,
        empty_detail=empty_detail,
        ledgers=ledgers,
    )

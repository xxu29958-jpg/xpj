"""Plan and insight row builders for the Desktop product projection."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas._desktop_product import DesktopProductRow
from app.services._desktop_product_labels import (
    _STATUS_LABELS,
    _field,
    _goal_progress_label,
    _goal_status_label,
    _income_frequency_label,
    _income_source_label,
    _iso,
    _money,
    _temporal_precision,
)
from app.services.budget_service import get_monthly_budget
from app.services.data_quality_service import data_quality_summary
from app.services.goal_service import list_goals
from app.services.income_plan_service import list_income_plans
from app.services.recurring_service import list_recurring_items
from app.services.reports_service import reports_overview
from app.services.time_service import current_month

_ROW_LIMIT = 200
_TIMEZONE = "Asia/Shanghai"


def _budget_rows(
    db: Session,
    *,
    ledger_id: str,
    month: str,
    currency_code: str,
) -> list[DesktopProductRow]:
    budget = get_monthly_budget(
        db,
        tenant_id=ledger_id,
        month=month,
        timezone_name=_TIMEZONE,
    )
    if not budget.configured:
        return []
    return [
        DesktopProductRow(
            key=f"budget:{month}",
            kind="budget",
            title=f"{month} 月度预算",
            subtitle=f"已使用 {_money(budget.spent_amount_cents, currency_code)}",
            status="configured",
            status_label=_STATUS_LABELS["configured"],
            amount_minor=budget.total_amount_cents,
            currency_code=currency_code,
            occurred_at=_iso(budget.updated_at),
            occurred_precision=_temporal_precision(budget.updated_at),
            fields=[
                _field("预算总额", _money(budget.total_amount_cents, currency_code)),
                _field("已使用", _money(budget.spent_amount_cents, currency_code)),
                _field("剩余", _money(budget.remaining_amount_cents, currency_code)),
                _field("固定支出", _money(budget.fixed_amount_cents, currency_code)),
                _field(
                    "非月度预留",
                    _money(budget.non_monthly_amount_cents, currency_code),
                ),
            ],
        )
    ]


def _goal_rows(
    db: Session,
    *,
    ledger_id: str,
    month: str,
    currency_code: str,
) -> list[DesktopProductRow]:
    goals = list_goals(
        db,
        tenant_id=ledger_id,
        month=month,
        timezone_name=_TIMEZONE,
    )
    return [
        DesktopProductRow(
            key=f"goal:{goal.public_id}",
            kind="goal",
            title=goal.name,
            subtitle=goal.category or "全账本",
            status=goal.progress_state,
            status_label=(f"{goal.progress_percent or 0}% · {_goal_progress_label(goal.progress_state)}"),
            amount_minor=goal.target_amount_cents,
            currency_code=currency_code,
            occurred_at=_iso(goal.updated_at),
            occurred_precision=_temporal_precision(goal.updated_at),
            fields=[
                _field("目标范围", goal.category or "全账本"),
                _field("目标金额", _money(goal.target_amount_cents, currency_code)),
                _field("已使用", _money(goal.spent_amount_cents, currency_code)),
                _field("剩余", _money(goal.remaining_amount_cents, currency_code)),
                _field("状态", _goal_status_label(goal.status)),
            ],
        )
        for goal in goals
    ]


def _income_plan_rows(
    db: Session,
    *,
    ledger_id: str,
    currency_code: str,
) -> list[DesktopProductRow]:
    income_rows = list_income_plans(db, tenant_id=ledger_id)
    rows: list[DesktopProductRow] = []
    for income in income_rows:
        frequency_label = _income_frequency_label(income.frequency)
        rows.append(
            DesktopProductRow(
                key=f"income:{income.public_id}",
                kind="income",
                title=income.label,
                subtitle=f"收入计划 · {frequency_label}",
                status=income.status,
                status_label=_STATUS_LABELS.get(income.status, income.status),
                amount_minor=income.amount_cents,
                currency_code=currency_code,
                occurred_at=_iso(income.updated_at),
                occurred_precision=_temporal_precision(income.updated_at),
                fields=[
                    _field("收入类型", _income_source_label(income.source_type)),
                    _field("频率", frequency_label),
                    _field("到账月份", income.income_month),
                    _field("到账日", f"{income.pay_day} 日"),
                ],
            )
        )
    return rows


def _recurring_plan_rows(
    db: Session,
    *,
    ledger_id: str,
    currency_code: str,
) -> list[DesktopProductRow]:
    recurring_rows = list_recurring_items(db, tenant_id=ledger_id)
    return [
        DesktopProductRow(
            key=f"recurring:{item.public_id}",
            kind="recurring",
            title=item.merchant_name,
            subtitle="固定支出 · 每月",
            status=item.status,
            status_label=_STATUS_LABELS.get(item.status, item.status),
            amount_minor=item.baseline_amount_cents,
            currency_code=currency_code,
            occurred_at=_iso(item.next_expected_date or item.updated_at),
            occurred_precision=_temporal_precision(item.next_expected_date or item.updated_at),
            fields=[
                _field("基准金额", _money(item.baseline_amount_cents, currency_code)),
                _field("最近金额", _money(item.last_amount_cents, currency_code)),
                _field("出现次数", item.occurrence_count),
                _field("下次预计", _iso(item.next_expected_date)),
                _field("置信度", item.confidence),
            ],
        )
        for item in recurring_rows
    ]


def plan_rows(
    db: Session,
    ledger_id: str,
    *,
    currency_code: str,
) -> tuple[list[DesktopProductRow], int]:
    month = current_month(_TIMEZONE)
    rows = [
        *_budget_rows(
            db,
            ledger_id=ledger_id,
            month=month,
            currency_code=currency_code,
        ),
        *_goal_rows(
            db,
            ledger_id=ledger_id,
            month=month,
            currency_code=currency_code,
        ),
        *_income_plan_rows(
            db,
            ledger_id=ledger_id,
            currency_code=currency_code,
        ),
        *_recurring_plan_rows(
            db,
            ledger_id=ledger_id,
            currency_code=currency_code,
        ),
    ]
    return rows[:_ROW_LIMIT], len(rows)


def _insight_metric(
    *,
    key: str,
    title: str,
    value: int,
    detail: str,
    attention: bool,
) -> DesktopProductRow:
    status = "attention" if attention else "healthy"
    return DesktopProductRow(
        key=f"quality:{key}",
        kind="quality_metric",
        title=title,
        subtitle=detail,
        status=status,
        status_label=_STATUS_LABELS[status],
        value_text=f"{value} 项",
        fields=[
            _field("当前数量", value),
            _field("判定", _STATUS_LABELS[status]),
            _field("说明", detail),
        ],
    )


def insights_rows(
    db: Session,
    ledger_id: str,
    *,
    currency_code: str,
) -> tuple[list[DesktopProductRow], int]:
    month = current_month(_TIMEZONE)
    quality = data_quality_summary(db, tenant_id=ledger_id)
    report = reports_overview(
        db,
        month=month,
        tenant_id=ledger_id,
        timezone_name=_TIMEZONE,
        granularity="day",
    )
    rows = [
        DesktopProductRow(
            key=f"report:{month}",
            kind="report_summary",
            title=f"{month} 月度概览",
            subtitle=f"{report['count']} 笔已确认流水",
            status="healthy" if report["count"] else "empty",
            status_label=_STATUS_LABELS["healthy" if report["count"] else "empty"],
            amount_minor=int(report["total_amount_cents"]),
            currency_code=currency_code,
            occurred_at=_iso(quality.generated_at),
            occurred_precision=_temporal_precision(quality.generated_at),
            fields=[
                _field(
                    "本月总额",
                    _money(int(report["total_amount_cents"]), currency_code),
                ),
                _field("本月笔数", report["count"]),
                _field(
                    "上月总额",
                    _money(
                        int(report["previous_total_amount_cents"]),
                        currency_code,
                    ),
                ),
                _field(
                    "去年同月",
                    _money(
                        int(report["year_over_year_total_amount_cents"]),
                        currency_code,
                    ),
                ),
            ],
        ),
        _insight_metric(
            key="missing_amount",
            title="待补金额",
            value=quality.missing_amount,
            detail="待确认票据中尚未填写金额的条目。",
            attention=quality.missing_amount > 0,
        ),
        _insight_metric(
            key="missing_merchant",
            title="待补商家",
            value=quality.missing_merchant,
            detail="待确认票据中尚未填写商家的条目。",
            attention=quality.missing_merchant > 0,
        ),
        _insight_metric(
            key="suspected_duplicates",
            title="疑似重复",
            value=quality.suspected_duplicates,
            detail="需要人工判断是否重复的待确认票据。",
            attention=quality.suspected_duplicates > 0,
        ),
        _insight_metric(
            key="confirmed_without_image",
            title="无可用图片",
            value=quality.confirmed_without_image,
            detail="已确认但原图缺失或已按策略清理的流水。",
            attention=quality.confirmed_without_image > 0,
        ),
    ]
    return rows, len(rows)

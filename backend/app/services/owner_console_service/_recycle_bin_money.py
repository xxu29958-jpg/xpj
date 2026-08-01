"""Money labels used by the Owner Console recycle-bin projection."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, BudgetCategory, Goal, MonthlyIncomePlan
from app.money_contract import projection_sum_to_int
from app.services.currency_common import minor_amount_label


def income_detail(item: MonthlyIncomePlan, *, currency_code: str) -> str:
    frequency = "每月固定" if item.frequency == "monthly" else f"{item.income_month} 到账"
    return f"{frequency} · {money(item.amount_cents, currency_code)} · {item.pay_day} 号"


def goal_detail(item: Goal, *, currency_code: str) -> str:
    if item.goal_type == "debt_repayment":
        return "还债目标"
    scope = item.category or "总支出"
    return f"{item.month} · {scope} · 目标 {money(item.target_amount_cents, currency_code)}"


def budget_detail(
    db: Session,
    item: Budget,
    *,
    currency_code: str,
) -> str:
    category_count = db.scalar(
        select(func.count(BudgetCategory.id))
        .where(BudgetCategory.tenant_id == item.tenant_id)
        .where(BudgetCategory.month == item.month)
    )
    total = money(item.total_amount_cents, currency_code)
    return f"总预算 {total} · 分类预算 {int(category_count or 0)} 项"


def money(amount_cents: int, currency_code: str) -> str:
    value = projection_sum_to_int(amount_cents, label="owner_recycle_bin.money")
    return minor_amount_label(value, currency_code)


__all__ = ["budget_detail", "goal_detail", "income_detail", "money"]

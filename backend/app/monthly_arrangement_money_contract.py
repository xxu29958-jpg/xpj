"""New arrangement facts supplement the frozen C07 v1 money inventory."""

from sqlalchemy import CheckConstraint

from app.money_contract_types import MoneyColumn, MoneySign

MONTHLY_ARRANGEMENT_MONEY_COLUMNS = tuple(
    MoneyColumn(table, column, MoneySign.NONNEGATIVE, False,
        check_table="monthly_arrangement_rev" if table.endswith("_revisions") else "monthly_arrangement")
    for table in ("monthly_arrangements", "monthly_arrangement_revisions")
    for column in ("reserved_buffer_cents", "savings_target_cents")
)


def monthly_arrangement_money_checks(table: str) -> tuple[CheckConstraint, ...]:
    return tuple(CheckConstraint(check.predicate, name=check.name)
        for column in MONTHLY_ARRANGEMENT_MONEY_COLUMNS if column.table == table for check in column.checks)

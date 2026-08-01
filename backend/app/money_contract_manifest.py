"""Frozen ADR-0073 C07 stored-money manifest."""

from __future__ import annotations

from app.money_contract_types import (
    MONEY_AGGREGATE_MAX,
    MONEY_MINOR_MAX,
    MoneyCheck,
    MoneyColumn,
    MoneySign,
    RemovedMoneyCheck,
)

GOAL_MONTH_SHAPE_CHECK_V1 = MoneyCheck(
    "goals",
    "month",
    "ck_goals_month_format",
    (
        "(goal_type = 'spending_limit' AND month IS NOT NULL AND "
        "length(month) = 7) OR "
        "(goal_type = 'debt_repayment' AND month IS NULL)"
    ),
)


# Permanent stored-fact contract for the C07 release.
MONEY_COLUMNS_V1: tuple[MoneyColumn, ...] = (
    MoneyColumn("bill_split_invitations", "amount_cents", MoneySign.POSITIVE, False),
    MoneyColumn(
        "bill_split_invitations",
        "original_amount_minor",
        MoneySign.POSITIVE,
        True,
    ),
    MoneyColumn("budget_categories", "amount_cents", MoneySign.NONNEGATIVE, False),
    MoneyColumn("budgets", "non_monthly_amount_cents", MoneySign.NONNEGATIVE, False),
    MoneyColumn("budgets", "rollover_amount_cents", MoneySign.SIGNED, False),
    MoneyColumn("budgets", "total_amount_cents", MoneySign.NONNEGATIVE, False),
    MoneyColumn("category_rules", "amount_max_cents", MoneySign.NONNEGATIVE, True),
    MoneyColumn("category_rules", "amount_min_cents", MoneySign.NONNEGATIVE, True),
    MoneyColumn("csv_import_rows", "amount_cents", MoneySign.NONNEGATIVE, True),
    MoneyColumn(
        "csv_import_rows", "original_amount_minor", MoneySign.NONNEGATIVE, True
    ),
    MoneyColumn(
        "debt_adjustments", "amount_cents", MoneySign.SIGNED, False, nonzero=True
    ),
    # Forgiveness is not client-entered single-fact money. It snapshots the
    # authoritative remaining fold into one append-only fact, so its envelope
    # is the aggregate wire bound. Older binaries reject this Alembic revision
    # before serving DML; the server-derived fold therefore uses the aggregate
    # wire envelope rather than the single-command envelope.
    MoneyColumn(
        "debt_forgivenesses",
        "amount_cents",
        MoneySign.POSITIVE,
        False,
        final_predicate_override=(
            f"amount_cents BETWEEN 1 AND {MONEY_AGGREGATE_MAX}"
        ),
    ),
    MoneyColumn("debts", "original_amount_minor", MoneySign.POSITIVE, True),
    MoneyColumn("debts", "principal_amount_cents", MoneySign.POSITIVE, False),
    MoneyColumn(
        "expense_items",
        "amount_cents",
        MoneySign.SIGNED,
        True,
        final_predicate_override=(
            "amount_cents IS NULL OR ("
            "(kind = 'discount' AND "
            f"amount_cents BETWEEN {-MONEY_MINOR_MAX} AND 0) OR "
            "(kind IN ('product', 'tax', 'service_fee') AND "
            f"amount_cents BETWEEN 0 AND {MONEY_MINOR_MAX})"
            ")"
        ),
    ),
    MoneyColumn("expense_items", "unit_price_cents", MoneySign.NONNEGATIVE, True),
    # The released pre-C07 API accepted zero-valued split rows.  Preserve
    # those historical facts during the expand migration; C07 command
    # validation is stricter and rejects new zero splits at the service edge.
    MoneyColumn("expense_splits", "amount_cents", MoneySign.NONNEGATIVE, False),
    MoneyColumn("expenses", "amount_cents", MoneySign.NONNEGATIVE, True),
    MoneyColumn(
        "expenses", "original_amount_minor", MoneySign.NONNEGATIVE, True
    ),
    MoneyColumn(
        "goals",
        "target_amount_cents",
        MoneySign.POSITIVE,
        True,
        final_predicate_override=(
            "(goal_type = 'spending_limit' AND "
            "target_amount_cents IS NOT NULL AND "
            f"(target_amount_cents BETWEEN 1 AND {MONEY_MINOR_MAX})) OR "
            "(goal_type = 'debt_repayment' AND target_amount_cents IS NULL)"
        ),
        additional_checks=(GOAL_MONTH_SHAPE_CHECK_V1,),
    ),
    MoneyColumn(
        "member_repayment_proposals",
        "confirmed_amount_cents",
        MoneySign.POSITIVE,
        True,
        check_table="mrp",
    ),
    MoneyColumn(
        "member_repayment_proposals",
        "original_amount_minor",
        MoneySign.POSITIVE,
        True,
        check_table="mrp",
    ),
    MoneyColumn(
        "member_repayment_proposals",
        "proposed_amount_cents",
        MoneySign.POSITIVE,
        False,
        check_table="mrp",
    ),
    MoneyColumn(
        "monthly_income_plans", "amount_cents", MoneySign.NONNEGATIVE, False
    ),
    MoneyColumn("ocr_facts", "parsed_amount_cents", MoneySign.NONNEGATIVE, True),
    MoneyColumn(
        "recurring_items", "baseline_amount_cents", MoneySign.POSITIVE, False
    ),
    MoneyColumn("recurring_items", "last_amount_cents", MoneySign.POSITIVE, False),
    MoneyColumn("repayment_drafts", "amount_cents", MoneySign.POSITIVE, False),
    MoneyColumn("repayments", "amount_cents", MoneySign.POSITIVE, False),
    MoneyColumn("repayments", "original_amount_minor", MoneySign.POSITIVE, True),
)

MONEY_FINAL_CHECKS_V1: tuple[MoneyCheck, ...] = tuple(
    check for column in MONEY_COLUMNS_V1 for check in column.checks
)
MONEY_REMOVED_LEGACY_CHECKS_V1: tuple[RemovedMoneyCheck, ...] = (
    RemovedMoneyCheck(
        "bill_split_invitations",
        "ck_bill_split_invitations_amount_positive",
    ),
    RemovedMoneyCheck(
        "budget_categories",
        "ck_budget_categories_amount_non_negative",
    ),
    RemovedMoneyCheck("budgets", "ck_budgets_total_non_negative"),
    RemovedMoneyCheck("budgets", "ck_budgets_non_monthly_non_negative"),
    RemovedMoneyCheck(
        "csv_import_rows",
        "ck_csv_import_rows_amount_non_negative",
    ),
    RemovedMoneyCheck(
        "debt_forgivenesses",
        "ck_debt_forgivenesses_amount_positive",
    ),
    RemovedMoneyCheck("debts", "ck_debts_principal_positive"),
    RemovedMoneyCheck("expense_items", "ck_expense_items_amount_by_kind"),
    RemovedMoneyCheck(
        "expense_items",
        "ck_expense_items_unit_price_non_negative",
    ),
    RemovedMoneyCheck(
        "expense_splits",
        "ck_expense_splits_amount_non_negative",
    ),
    RemovedMoneyCheck("expenses", "ck_expenses_amount_non_negative"),
    RemovedMoneyCheck(
        "expenses",
        "ck_expenses_original_amount_non_negative",
    ),
    RemovedMoneyCheck("goals", "ck_goals_target_positive"),
    RemovedMoneyCheck(
        "member_repayment_proposals",
        "ck_member_repayment_proposals_amount_positive",
    ),
    RemovedMoneyCheck(
        "monthly_income_plans",
        "ck_monthly_income_plans_amount_non_negative",
    ),
    RemovedMoneyCheck("repayment_drafts", "ck_repayment_drafts_amount_positive"),
    RemovedMoneyCheck("repayments", "ck_repayments_amount_positive"),
)
assert len(MONEY_COLUMNS_V1) == 30
assert all(column.server_default is None for column in MONEY_COLUMNS_V1)
assert len({(c.table, c.column) for c in MONEY_COLUMNS_V1}) == 30
assert tuple(sorted(MONEY_COLUMNS_V1, key=lambda c: (c.table, c.column))) == (
    MONEY_COLUMNS_V1
)
_all_check_names = tuple(check.name for check in MONEY_FINAL_CHECKS_V1)
assert len(set(_all_check_names)) == len(_all_check_names) == 31
assert all(len(name.encode("utf-8")) <= 63 for name in _all_check_names)
_removed_legacy_check_keys = tuple(
    (check.table, check.name) for check in MONEY_REMOVED_LEGACY_CHECKS_V1
)
assert len(set(_removed_legacy_check_keys)) == len(_removed_legacy_check_keys) == 17
assert set(_removed_legacy_check_keys).isdisjoint(
    (check.table, check.name) for check in MONEY_FINAL_CHECKS_V1
)

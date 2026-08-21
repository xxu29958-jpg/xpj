"""ADR-0073: widen canonical money columns from INTEGER to BIGINT.

This forward-only PostgreSQL transaction takes the schema advisory lease and
ACCESS EXCLUSIVE locks on every affected table before validation or rewrite.
INTEGER-to-BIGINT may rewrite each table and its indexes; the lifecycle
preflight must therefore verify a pre-DDL recovery point, free disk and the
maintenance window before invoking Alembic. Canonical amount values and receipt
assets are not mutated. This revision is deliberately limited to the frozen
30-column money manifest; currency authority and import/OCR provenance changes
belong to later, independently reviewed revisions.
Alembic executes this revision inside a caller-owned, pre-armed transaction;
the widened columns expose the contracted 9e12 command envelope.

Revision ID: 20260729_0001
Revises: 20260722_0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0001"
down_revision: str | Sequence[str] | None = "20260722_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen rows:
# table, column, nullable, final name/predicate, reserved check slots.
# Every active money check is the permanent ADR-0073 bound; the two reserved slots
# remain null to keep the migration's frozen tuple shape explicit.
_MANIFEST_ROWS: tuple[
    tuple[str, str, bool, str, str, str | None, str | None], ...
] = (
    (
        "bill_split_invitations",
        "amount_cents",
        False,
        "ck_bill_split_invitations_amount_cents_money_bounds",
        "amount_cents BETWEEN 1 AND 9000000000000",
        None,
        None,
    ),
    (
        "bill_split_invitations",
        "original_amount_minor",
        True,
        "ck_bill_split_invitations_original_amount_minor_money_bounds",
        "original_amount_minor IS NULL OR (original_amount_minor BETWEEN 1 AND 9000000000000)",
        None,
        None,
    ),
    (
        "budget_categories",
        "amount_cents",
        False,
        "ck_budget_categories_amount_cents_money_bounds",
        "amount_cents BETWEEN 0 AND 9000000000000",
        None,
        None,
    ),
    (
        "budgets",
        "non_monthly_amount_cents",
        False,
        "ck_budgets_non_monthly_amount_cents_money_bounds",
        "non_monthly_amount_cents BETWEEN 0 AND 9000000000000",
        None,
        None,
    ),
    (
        "budgets",
        "rollover_amount_cents",
        False,
        "ck_budgets_rollover_amount_cents_money_bounds",
        "rollover_amount_cents BETWEEN -9000000000000 AND 9000000000000",
        None,
        None,
    ),
    (
        "budgets",
        "total_amount_cents",
        False,
        "ck_budgets_total_amount_cents_money_bounds",
        "total_amount_cents BETWEEN 0 AND 9000000000000",
        None,
        None,
    ),
    (
        "category_rules",
        "amount_max_cents",
        True,
        "ck_category_rules_amount_max_cents_money_bounds",
        "amount_max_cents IS NULL OR (amount_max_cents BETWEEN 0 AND 9000000000000)",
        None,
        None,
    ),
    (
        "category_rules",
        "amount_min_cents",
        True,
        "ck_category_rules_amount_min_cents_money_bounds",
        "amount_min_cents IS NULL OR (amount_min_cents BETWEEN 0 AND 9000000000000)",
        None,
        None,
    ),
    (
        "csv_import_rows",
        "amount_cents",
        True,
        "ck_csv_import_rows_amount_cents_money_bounds",
        "amount_cents IS NULL OR (amount_cents BETWEEN 0 AND 9000000000000)",
        None,
        None,
    ),
    (
        "csv_import_rows",
        "original_amount_minor",
        True,
        "ck_csv_import_rows_original_amount_minor_money_bounds",
        "original_amount_minor IS NULL OR (original_amount_minor BETWEEN 0 AND 9000000000000)",
        None,
        None,
    ),
    (
        "debt_adjustments",
        "amount_cents",
        False,
        "ck_debt_adjustments_amount_cents_money_bounds",
        "amount_cents <> 0 AND (amount_cents BETWEEN -9000000000000 AND 9000000000000)",
        None,
        None,
    ),
    (
        "debt_forgivenesses",
        "amount_cents",
        False,
        "ck_debt_forgivenesses_amount_cents_money_bounds",
        "amount_cents BETWEEN 1 AND 9007199254740991",
        None,
        None,
    ),
    (
        "debts",
        "original_amount_minor",
        True,
        "ck_debts_original_amount_minor_money_bounds",
        "original_amount_minor IS NULL OR (original_amount_minor BETWEEN 1 AND 9000000000000)",
        None,
        None,
    ),
    (
        "debts",
        "principal_amount_cents",
        False,
        "ck_debts_principal_amount_cents_money_bounds",
        "principal_amount_cents BETWEEN 1 AND 9000000000000",
        None,
        None,
    ),
    (
        "expense_items",
        "amount_cents",
        True,
        "ck_expense_items_amount_cents_money_bounds",
        "amount_cents IS NULL OR ((kind = 'discount' AND amount_cents BETWEEN -9000000000000 AND 0) OR (kind IN ('product', 'tax', 'service_fee') AND amount_cents BETWEEN 0 AND 9000000000000))",
        None,
        None,
    ),
    (
        "expense_items",
        "unit_price_cents",
        True,
        "ck_expense_items_unit_price_cents_money_bounds",
        "unit_price_cents IS NULL OR (unit_price_cents BETWEEN 0 AND 9000000000000)",
        None,
        None,
    ),
    (
        "expense_splits",
        "amount_cents",
        False,
        "ck_expense_splits_amount_cents_money_bounds",
        "amount_cents BETWEEN 0 AND 9000000000000",
        None,
        None,
    ),
    (
        "expenses",
        "amount_cents",
        True,
        "ck_expenses_amount_cents_money_bounds",
        "amount_cents IS NULL OR (amount_cents BETWEEN 0 AND 9000000000000)",
        None,
        None,
    ),
    (
        "expenses",
        "original_amount_minor",
        True,
        "ck_expenses_original_amount_minor_money_bounds",
        "original_amount_minor IS NULL OR (original_amount_minor BETWEEN 0 AND 9000000000000)",
        None,
        None,
    ),
    (
        "goals",
        "target_amount_cents",
        True,
        "ck_goals_target_amount_cents_money_bounds",
        "(goal_type = 'spending_limit' AND target_amount_cents IS NOT NULL AND (target_amount_cents BETWEEN 1 AND 9000000000000)) OR (goal_type = 'debt_repayment' AND target_amount_cents IS NULL)",
        "ck_goals_month_format",
        "(goal_type = 'spending_limit' AND month IS NOT NULL AND length(month) = 7) OR (goal_type = 'debt_repayment' AND month IS NULL)",
    ),
    (
        "member_repayment_proposals",
        "confirmed_amount_cents",
        True,
        "ck_mrp_confirmed_amount_cents_money_bounds",
        "confirmed_amount_cents IS NULL OR (confirmed_amount_cents BETWEEN 1 AND 9000000000000)",
        None,
        None,
    ),
    (
        "member_repayment_proposals",
        "original_amount_minor",
        True,
        "ck_mrp_original_amount_minor_money_bounds",
        "original_amount_minor IS NULL OR (original_amount_minor BETWEEN 1 AND 9000000000000)",
        None,
        None,
    ),
    (
        "member_repayment_proposals",
        "proposed_amount_cents",
        False,
        "ck_mrp_proposed_amount_cents_money_bounds",
        "proposed_amount_cents BETWEEN 1 AND 9000000000000",
        None,
        None,
    ),
    (
        "monthly_income_plans",
        "amount_cents",
        False,
        "ck_monthly_income_plans_amount_cents_money_bounds",
        "amount_cents BETWEEN 0 AND 9000000000000",
        None,
        None,
    ),
    (
        "ocr_facts",
        "parsed_amount_cents",
        True,
        "ck_ocr_facts_parsed_amount_cents_money_bounds",
        "parsed_amount_cents IS NULL OR (parsed_amount_cents BETWEEN 0 AND 9000000000000)",
        None,
        None,
    ),
    (
        "recurring_items",
        "baseline_amount_cents",
        False,
        "ck_recurring_items_baseline_amount_cents_money_bounds",
        "baseline_amount_cents BETWEEN 1 AND 9000000000000",
        None,
        None,
    ),
    (
        "recurring_items",
        "last_amount_cents",
        False,
        "ck_recurring_items_last_amount_cents_money_bounds",
        "last_amount_cents BETWEEN 1 AND 9000000000000",
        None,
        None,
    ),
    (
        "repayment_drafts",
        "amount_cents",
        False,
        "ck_repayment_drafts_amount_cents_money_bounds",
        "amount_cents BETWEEN 1 AND 9000000000000",
        None,
        None,
    ),
    (
        "repayments",
        "amount_cents",
        False,
        "ck_repayments_amount_cents_money_bounds",
        "amount_cents BETWEEN 1 AND 9000000000000",
        None,
        None,
    ),
    (
        "repayments",
        "original_amount_minor",
        True,
        "ck_repayments_original_amount_minor_money_bounds",
        "original_amount_minor IS NULL OR (original_amount_minor BETWEEN 1 AND 9000000000000)",
        None,
        None,
    ),
)
_MANIFEST: tuple[
    tuple[
        str,
        str,
        bool,
        str,
        str,
        str | None,
        str | None,
        str | None,
    ],
    ...,
] = tuple((*row, None) for row in _MANIFEST_ROWS)

_LEGACY_CHECKS: dict[str, tuple[tuple[str, str], ...]] = {
    "bill_split_invitations": (
        ("ck_bill_split_invitations_amount_positive", "amount_cents > 0"),
    ),
    "budget_categories": (
        (
            "ck_budget_categories_amount_non_negative",
            "amount_cents >= 0",
        ),
    ),
    "budgets": (
        ("ck_budgets_total_non_negative", "total_amount_cents >= 0"),
        (
            "ck_budgets_non_monthly_non_negative",
            "non_monthly_amount_cents >= 0",
        ),
    ),
    "csv_import_rows": (
        (
            "ck_csv_import_rows_amount_non_negative",
            "amount_cents IS NULL OR amount_cents >= 0",
        ),
    ),
    "debt_forgivenesses": (
        (
            "ck_debt_forgivenesses_amount_positive",
            "amount_cents > 0",
        ),
    ),
    "debts": (
        ("ck_debts_principal_positive", "principal_amount_cents > 0"),
    ),
    "expense_items": (
        (
            "ck_expense_items_amount_by_kind",
            "(kind = 'product' AND (amount_cents IS NULL OR amount_cents >= 0)) "
            "OR (kind = 'discount' AND (amount_cents IS NULL OR amount_cents <= 0)) "
            "OR (kind IN ('tax', 'service_fee') "
            "AND (amount_cents IS NULL OR amount_cents >= 0))",
        ),
        (
            "ck_expense_items_unit_price_non_negative",
            "unit_price_cents IS NULL OR unit_price_cents >= 0",
        ),
    ),
    "expense_splits": (
        (
            "ck_expense_splits_amount_non_negative",
            "amount_cents >= 0",
        ),
    ),
    "expenses": (
        (
            "ck_expenses_amount_non_negative",
            "amount_cents IS NULL OR amount_cents >= 0",
        ),
        (
            "ck_expenses_original_amount_non_negative",
            "original_amount_minor IS NULL OR original_amount_minor >= 0",
        ),
    ),
    "goals": (
        (
            "ck_goals_target_positive",
            "goal_type <> 'spending_limit' OR target_amount_cents > 0",
        ),
    ),
    "member_repayment_proposals": (
        (
            "ck_member_repayment_proposals_amount_positive",
            "proposed_amount_cents > 0",
        ),
    ),
    "monthly_income_plans": (
        (
            "ck_monthly_income_plans_amount_non_negative",
            "amount_cents >= 0",
        ),
    ),
    "repayment_drafts": (
        ("ck_repayment_drafts_amount_positive", "amount_cents > 0"),
    ),
    "repayments": (
        ("ck_repayments_amount_positive", "amount_cents > 0"),
    ),
}
_REPLACED_CHECKS: dict[str, tuple[tuple[str, str], ...]] = {
    "goals": (
        (
            "ck_goals_month_format",
            "goal_type <> 'spending_limit' OR length(month) = 7",
        ),
    ),
}

_TABLES = tuple(sorted({row[0] for row in _MANIFEST}))
_PROBE_NAME = "__xpj_money_bigint_check_probe"


def _quoted(bind: sa.engine.Connection, identifier: str) -> str:
    return bind.dialect.identifier_preparer.quote_identifier(identifier)


def _constraint_state(bind: sa.engine.Connection, table: str, name: str) -> tuple[str, bool, bool] | None:
    row = bind.execute(
        sa.text(
            "SELECT pg_get_expr(c.conbin, c.conrelid, true), "
            "c.convalidated, c.connoinherit "
            "FROM pg_constraint c "
            "WHERE c.conrelid = to_regclass(:table) "
            "AND c.contype = 'c' AND c.conname = :name"
        ),
        {"table": f"public.{table}", "name": name},
    ).one_or_none()
    return None if row is None else (str(row[0]), bool(row[1]), bool(row[2]))


def _read_only_check_expression(
    bind: sa.engine.Connection,
    *,
    table: str,
    predicate: str,
) -> str:
    alias = "c07_source_expected"
    plan = bind.scalar(
        sa.text(
            "EXPLAIN (VERBOSE, FORMAT JSON, COSTS FALSE) "
            f"SELECT 1 FROM {_quoted(bind, table)} AS {alias} "
            f"WHERE ({predicate})"
        )
    )
    try:
        expression = str(plan[0]["Plan"]["Filter"])
    except (IndexError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"C07 could not parse frozen source CHECK for {table}"
        ) from exc
    return expression.replace(f"{alias}.", "").replace(
        f'"{alias}".',
        "",
    )


def _verify_legacy_checks(bind: sa.engine.Connection) -> None:
    for source_checks in (_LEGACY_CHECKS, _REPLACED_CHECKS):
        for table, checks in source_checks.items():
            for name, predicate in checks:
                state = _constraint_state(bind, table, name)
                if state is None:
                    raise RuntimeError(
                        "C07 frozen source CHECK is missing: "
                        f"{table}.{name}"
                    )
                actual_predicate, validated, no_inherit = state
                expected = _read_only_check_expression(
                    bind,
                    table=table,
                    predicate=predicate,
                )
                actual = _read_only_check_expression(
                    bind,
                    table=table,
                    predicate=actual_predicate,
                )
                if (
                    actual != expected
                    or not validated
                    or no_inherit
                ):
                    raise RuntimeError(
                        "C07 frozen source CHECK differs: "
                        f"{table}.{name}"
                    )


def _expected_expression(bind: sa.engine.Connection, table: str, predicate: str) -> str:
    quoted_table = _quoted(bind, table)
    quoted_probe = _quoted(bind, _PROBE_NAME)
    op.execute(f"ALTER TABLE {quoted_table} ADD CONSTRAINT {quoted_probe} CHECK ({predicate}) NOT VALID")
    try:
        state = _constraint_state(bind, table, _PROBE_NAME)
        if state is None:
            raise RuntimeError("C07 failed to parse expected CHECK predicate")
        return state[0]
    finally:
        op.execute(f"ALTER TABLE {quoted_table} DROP CONSTRAINT {quoted_probe}")


def _acquire_barrier(bind: sa.engine.Connection) -> None:
    timeout_ms = 20 * 60 * 1000
    timeout_rows = bind.execute(
        sa.text(
            "SELECT name, setting, unit FROM pg_catalog.pg_settings "
            "WHERE name IN ("
            "'transaction_timeout', 'statement_timeout', 'lock_timeout'"
            ")"
        )
    ).all()
    current_timeouts: dict[str, int] = {}
    for name, setting, unit in timeout_rows:
        if (
            str(name) in current_timeouts
            or str(name)
            not in {
                "transaction_timeout",
                "statement_timeout",
                "lock_timeout",
            }
            or str(unit) != "ms"
            or not str(setting).isascii()
            or not str(setting).isdecimal()
        ):
            raise RuntimeError("C07 PostgreSQL timeout authority is invalid")
        current_timeouts[str(name)] = int(str(setting))
    if set(current_timeouts) != {
        "transaction_timeout",
        "statement_timeout",
        "lock_timeout",
    }:
        raise RuntimeError("C07 requires PostgreSQL transaction_timeout")

    def bounded_timeout(name: str, maximum: int) -> int:
        current = current_timeouts[name]
        if current < 0:
            raise RuntimeError("C07 PostgreSQL timeout authority is invalid")
        return maximum if current == 0 else min(current, maximum)

    transaction_timeout_ms = current_timeouts["transaction_timeout"]
    if transaction_timeout_ms <= 0 or transaction_timeout_ms > 20 * 60 * 1000:
        raise RuntimeError(
            "C07 transaction_timeout was not armed before BEGIN"
        )
    statement_timeout_ms = bounded_timeout(
        "statement_timeout",
        timeout_ms,
    )
    lock_timeout_ms = bounded_timeout(
        "lock_timeout",
        min(timeout_ms, 5000),
    )
    op.execute(
        f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'"
    )
    op.execute(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'")
    locked = bind.scalar(
        sa.text("SELECT pg_try_advisory_xact_lock(hashtext(current_database()), hashtext('xiaopiaojia:schema'))")
    )
    if not locked:
        raise RuntimeError("C07 migration lease is busy")
    tables = ", ".join(_quoted(bind, table) for table in _TABLES)
    op.execute(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE")


def _column_types(bind: sa.engine.Connection) -> dict[tuple[str, str], str]:
    inspector = sa.inspect(bind)
    result: dict[tuple[str, str], str] = {}
    for row in _MANIFEST:
        (
            table,
            column,
            nullable,
            *_checks,
            server_default,
        ) = row
        if not inspector.has_table(table):
            raise RuntimeError(f"C07 missing table {table}")
        columns = {item["name"]: item for item in inspector.get_columns(table)}
        actual = columns.get(column)
        if actual is None:
            raise RuntimeError(f"C07 missing column {table}.{column}")
        if bool(actual["nullable"]) is not nullable:
            raise RuntimeError(
                f"C07 nullability mismatch {table}.{column}: expected={nullable}, actual={actual['nullable']}"
            )
        if actual.get("default") != server_default:
            raise RuntimeError(
                f"C07 server default mismatch {table}.{column}: "
                f"expected={server_default!r}"
            )
        catalog_shape = bind.execute(
            sa.text(
                "SELECT format_type(a.atttypid, a.atttypmod), "
                "a.attidentity, a.attgenerated, t.typtype "
                "FROM pg_attribute AS a "
                "JOIN pg_class AS c ON c.oid = a.attrelid "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "JOIN pg_type AS t ON t.oid = a.atttypid "
                "WHERE n.nspname = 'public' "
                "AND c.relname = :table "
                "AND a.attname = :column "
                "AND a.attnum > 0 AND NOT a.attisdropped"
            ),
            {"table": table, "column": column},
        ).one_or_none()
        if (
            catalog_shape is None
            or str(catalog_shape[1]) != ""
            or str(catalog_shape[2]) != ""
            or str(catalog_shape[3]) != "b"
        ):
            raise RuntimeError(
                f"C07 generated/identity/domain column mismatch "
                f"{table}.{column}"
            )
        raw = str(actual["type"]).lower()
        if "bigint" in raw or raw == "int8":
            result[(table, column)] = "int8"
        elif raw in {"integer", "int", "int4"}:
            result[(table, column)] = "int4"
        else:
            raise RuntimeError(f"C07 unexpected type {table}.{column}: {raw}")
    return result


def _scan_existing_rows(bind: sa.engine.Connection) -> None:
    violations: list[str] = []
    for (
        table,
        column,
        _nullable,
        _final_name,
        final,
        _hold_name,
        hold,
        _server_default,
    ) in _MANIFEST:
        for kind, predicate in (("final", final), ("hold", hold)):
            if predicate is None:
                continue
            count = bind.scalar(sa.text(f"SELECT count(*) FROM {_quoted(bind, table)} WHERE ({predicate}) IS NOT TRUE"))
            if count:
                violations.append(f"{table}.{column}:{kind}={int(count)}")
    if violations:
        raise RuntimeError(
            "C07 existing financial facts violate target shape: "
            + ", ".join(violations)
        )


def _expected_checks() -> tuple[tuple[str, str, str], ...]:
    checks: list[tuple[str, str, str]] = []
    for (
        table,
        _column,
        _nullable,
        final_name,
        final,
        hold_name,
        hold,
        _server_default,
    ) in _MANIFEST:
        checks.append((table, final_name, final))
        if hold_name is not None and hold is not None:
            checks.append((table, hold_name, hold))
    return tuple(checks)


def _verify_existing_checks(
    bind: sa.engine.Connection,
) -> tuple[dict[tuple[str, str], str], list[tuple[str, str, str]]]:
    expected: dict[tuple[str, str], str] = {}
    missing: list[tuple[str, str, str]] = []
    for table, name, predicate in _expected_checks():
        expression = _expected_expression(bind, table, predicate)
        expected[(table, name)] = expression
        state = _constraint_state(bind, table, name)
        if state is None:
            missing.append((table, name, predicate))
            continue
        actual_expression, validated, no_inherit = state
        if actual_expression != expression or not validated or no_inherit:
            raise RuntimeError(
                f"C07 constraint mismatch {table}.{name}: validated={validated}, no_inherit={no_inherit}"
            )
    return expected, missing


def _assert_target_checks_absent(bind: sa.engine.Connection) -> None:
    for table, name, _predicate in _expected_checks():
        if _constraint_state(bind, table, name) is not None:
            raise RuntimeError(f"C07 found target CHECK on int4 column: {table}.{name}")


def _widen(bind: sa.engine.Connection) -> None:
    for table in _TABLES:
        columns = [row[1] for row in _MANIFEST if row[0] == table]
        if not columns:
            continue
        clauses = ", ".join(f"ALTER COLUMN {_quoted(bind, column)} TYPE bigint" for column in columns)
        op.execute(f"ALTER TABLE {_quoted(bind, table)} {clauses}")


def _install_missing_checks(
    bind: sa.engine.Connection,
    missing: list[tuple[str, str, str]],
) -> None:
    for table, name, predicate in missing:
        op.execute(
            f"ALTER TABLE {_quoted(bind, table)} ADD CONSTRAINT {_quoted(bind, name)} CHECK ({predicate}) NOT VALID"
        )
    for table, name, _predicate in missing:
        op.execute(f"ALTER TABLE {_quoted(bind, table)} VALIDATE CONSTRAINT {_quoted(bind, name)}")


def _drop_legacy_checks(bind: sa.engine.Connection) -> None:
    for table, checks in _LEGACY_CHECKS.items():
        for name, _predicate in checks:
            op.execute(
                f"ALTER TABLE {_quoted(bind, table)} "
                f"DROP CONSTRAINT {_quoted(bind, name)}"
            )


def _drop_replaced_checks(bind: sa.engine.Connection) -> None:
    for table, checks in _REPLACED_CHECKS.items():
        for name, _predicate in checks:
            op.execute(
                f"ALTER TABLE {_quoted(bind, table)} "
                f"DROP CONSTRAINT {_quoted(bind, name)}"
            )


def _assert_final_shape(
    bind: sa.engine.Connection,
    expected: dict[tuple[str, str], str],
) -> None:
    for table, name, _predicate in _expected_checks():
        state = _constraint_state(bind, table, name)
        if state != (expected[(table, name)], True, False):
            raise RuntimeError(f"C07 post-check failed {table}.{name}")


def upgrade() -> None:
    bind = op.get_bind()
    _acquire_barrier(bind)
    types = _column_types(bind)
    states = set(types.values())
    if states not in ({"int4"}, {"int8"}):
        raise RuntimeError("C07 mixed int4/int8 state")

    _scan_existing_rows(bind)
    if states == {"int4"}:
        _verify_legacy_checks(bind)
        _drop_replaced_checks(bind)
        _assert_target_checks_absent(bind)
        _widen(bind)
    expected, missing = _verify_existing_checks(bind)
    _install_missing_checks(bind, missing)
    if states == {"int4"}:
        _drop_legacy_checks(bind)
    _assert_final_shape(bind, expected)
    if set(_column_types(bind).values()) != {"int8"}:
        raise RuntimeError("C07 post-check found a non-BIGINT money column")


def downgrade() -> None:
    raise RuntimeError("Money BIGINT migration is forward-only and cannot narrow to INTEGER")

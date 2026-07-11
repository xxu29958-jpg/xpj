"""Reconcile schema drift previously hidden by the runtime create_all bridge.

Revision ID: 20260711_0001
Revises: 20260630_0002

Forward-only: this revision makes the Alembic head match the current runtime
contract. Application rollback is governed by schema compatibility metadata;
startup never runs an automatic database downgrade.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260711_0001"
down_revision: str | Sequence[str] | None = "20260630_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REDUNDANT_PUBLIC_ID_UNIQUES = {
    "category_preferences": "uq_category_preferences_public_id",
    "debt_adjustments": "debt_adjustments_public_id_key",
    "debt_forgivenesses": "debt_forgivenesses_public_id_key",
    "debt_voids": "debt_voids_public_id_key",
    "debts": "debts_public_id_key",
    "member_repayment_proposals": "member_repayment_proposals_public_id_key",
    "merchant_catalog": "uq_merchant_catalog_public_id",
    "repayment_drafts": "repayment_drafts_public_id_key",
    "repayment_voids": "repayment_voids_public_id_key",
    "repayments": "repayments_public_id_key",
}


def _has_table(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _indexes(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _unique_constraints(bind, table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(bind).get_unique_constraints(table_name)
        if constraint.get("name")
    }


def _foreign_keys(bind, table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(bind).get_foreign_keys(table_name)
        if constraint.get("name")
    }


def _check_constraints(bind, table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(bind).get_check_constraints(table_name)
        if constraint.get("name")
    }


def _add_missing_columns(bind) -> None:
    additions = {
        "category_rules": (
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ),
        "ledger_audit_logs": (
            sa.Column("resource_type", sa.String(length=64), nullable=True),
            sa.Column("resource_public_id", sa.String(length=64), nullable=True),
        ),
        "merchant_aliases": (
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ),
    }
    for table_name, candidates in additions.items():
        if not _has_table(bind, table_name):
            continue
        existing = _columns(bind, table_name)
        for column in candidates:
            if column.name not in existing:
                op.add_column(table_name, column)


def _add_missing_checks(bind) -> None:
    table_name = "auth_tokens"
    constraint_name = "ck_auth_tokens_scope_valid"
    if not _has_table(bind, table_name):
        return
    if constraint_name in _check_constraints(bind, table_name):
        return
    invalid_scope = bind.scalar(
        sa.text(
            "SELECT scope FROM auth_tokens "
            "WHERE scope NOT IN ('app', 'admin') LIMIT 1"
        )
    )
    if invalid_scope is not None:
        raise RuntimeError(
            "auth_tokens contains an invalid scope; refusing to add "
            "ck_auth_tokens_scope_valid"
        )
    op.create_check_constraint(
        constraint_name,
        table_name,
        "scope IN ('app', 'admin')",
    )


def _add_missing_indexes(bind) -> None:
    if "uq_auth_tokens_active_principal" not in _indexes(bind, "auth_tokens"):
        op.create_index(
            "uq_auth_tokens_active_principal",
            "auth_tokens",
            ["account_id", "device_id", "ledger_id", "scope"],
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        )
    if "ix_category_rules_tenant_deleted" not in _indexes(bind, "category_rules"):
        op.create_index(
            "ix_category_rules_tenant_deleted",
            "category_rules",
            ["tenant_id", "deleted_at"],
        )
    if "uq_csv_import_rows_tenant_expense_id" not in _indexes(bind, "csv_import_rows"):
        op.create_index(
            "uq_csv_import_rows_tenant_expense_id",
            "csv_import_rows",
            ["tenant_id", "expense_id"],
            unique=True,
            postgresql_where=sa.text("expense_id IS NOT NULL"),
        )
    if "ix_expenses_image_perceptual_hash" not in _indexes(bind, "expenses"):
        op.create_index(
            "ix_expenses_image_perceptual_hash",
            "expenses",
            ["image_perceptual_hash"],
        )
    audit_index = "ix_ledger_audit_logs_resource_public_id"
    if audit_index not in _indexes(bind, "ledger_audit_logs"):
        op.create_index(audit_index, "ledger_audit_logs", ["resource_public_id"])


def _drop_redundant_objects(bind) -> None:
    expense_indexes = _indexes(bind, "expenses")
    if "ix_expenses_split_origin_invitation_id" in expense_indexes:
        op.drop_index("ix_expenses_split_origin_invitation_id", table_name="expenses")
    for table_name, constraint_name in _REDUNDANT_PUBLIC_ID_UNIQUES.items():
        if not _has_table(bind, table_name):
            continue
        if constraint_name in _unique_constraints(bind, table_name):
            op.drop_constraint(constraint_name, table_name, type_="unique")


def _replace_ocr_expense_foreign_key(bind) -> None:
    if not _has_table(bind, "ocr_facts"):
        return
    names = _foreign_keys(bind, "ocr_facts")
    if "fk_ocr_facts_expense" in names:
        op.drop_constraint("fk_ocr_facts_expense", "ocr_facts", type_="foreignkey")
    if "fk_ocr_facts_expense_tenant" not in names:
        op.create_foreign_key(
            "fk_ocr_facts_expense_tenant",
            "ocr_facts",
            "expenses",
            ["expense_id", "tenant_id"],
            ["id", "tenant_id"],
        )


def _advance_compatibility_metadata(bind) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO app_meta (key, value, updated_at) VALUES "
            "('schema_version', '1.2.0', CURRENT_TIMESTAMP), "
            "('schema_min_compatible', '1.2.0', CURRENT_TIMESTAMP) "
            "ON CONFLICT (key) DO UPDATE SET "
            "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    _add_missing_columns(bind)
    _add_missing_checks(bind)
    _add_missing_indexes(bind)
    _drop_redundant_objects(bind)
    _replace_ocr_expense_foreign_key(bind)
    _advance_compatibility_metadata(bind)


def downgrade() -> None:
    raise NotImplementedError("20260711_0001 is forward-only")

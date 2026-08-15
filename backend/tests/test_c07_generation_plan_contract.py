"""C07 product-policy projection inside the build-owned generation program."""

from __future__ import annotations

import hashlib
from pathlib import Path

import app.database_generation_c07_contract as maintenance

SOURCE_REVISION = "20260722_0001"
TARGET_REVISION = "20260729_0001"


def test_c07_plan_is_one_exact_release_edge() -> None:
    module_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / f"{TARGET_REVISION}_money_minor_bigint_expand.py"
    )
    contract = maintenance.build_c07_revision_contract(
        module_path=module_path,
        module_sha256=hashlib.sha256(module_path.read_bytes()).hexdigest(),
        source_revision=SOURCE_REVISION,
        target_revision=TARGET_REVISION,
    )
    plan = contract.revision_manifest
    revision = plan["revisions"][0]

    assert plan["source_revision"] == SOURCE_REVISION
    assert plan["target_revision"] == TARGET_REVISION
    assert revision["revision"] == TARGET_REVISION
    assert revision["down_revision"] == SOURCE_REVISION
    assert revision["transactionality"] == "postgresql_single_transaction"
    assert revision["reversibility"] == "forward_only"
    expected_removed_checks = {
        ("bill_split_invitations", "ck_bill_split_invitations_amount_positive"),
        ("budget_categories", "ck_budget_categories_amount_non_negative"),
        ("budgets", "ck_budgets_total_non_negative"),
        ("budgets", "ck_budgets_non_monthly_non_negative"),
        ("csv_import_rows", "ck_csv_import_rows_amount_non_negative"),
        ("debt_forgivenesses", "ck_debt_forgivenesses_amount_positive"),
        ("debts", "ck_debts_principal_positive"),
        ("expense_items", "ck_expense_items_amount_by_kind"),
        ("expense_items", "ck_expense_items_unit_price_non_negative"),
        ("expense_splits", "ck_expense_splits_amount_non_negative"),
        ("expenses", "ck_expenses_amount_non_negative"),
        ("expenses", "ck_expenses_original_amount_non_negative"),
        ("goals", "ck_goals_target_positive"),
        (
            "member_repayment_proposals",
            "ck_member_repayment_proposals_amount_positive",
        ),
        ("monthly_income_plans", "ck_monthly_income_plans_amount_non_negative"),
        ("repayment_drafts", "ck_repayment_drafts_amount_positive"),
        ("repayments", "ck_repayments_amount_positive"),
    }
    assert {
        (check.table, check.name)
        for check in maintenance.MONEY_REMOVED_LEGACY_CHECKS_V1
    } == expected_removed_checks
    expected_resources = {
        *(
            f"column:{contract.table}.{contract.column}:type=int8"
            for contract in maintenance.MONEY_COLUMNS_V1
        ),
        *(
            f"constraint:{check.table}.{check.name}:present_validated"
            for contract in maintenance.MONEY_COLUMNS_V1
            for check in contract.checks
        ),
        *(
            f"constraint:{check.table}.{check.name}:absent"
            for check in maintenance.MONEY_REMOVED_LEGACY_CHECKS_V1
        ),
        "meta:money_contract_phase=c07_money_minor_bigint_v1",
        "meta:money_c07_ceremony_id:present",
        "meta:money_c07_lifecycle_state:present",
    }
    assert set(revision["resources"]) == expected_resources
    assert len(revision["resources"]) == len(expected_resources) == 81
    assert not any("_c07_i4_hold" in resource for resource in revision["resources"])
    assert not hasattr(maintenance, "get_installed_maintenance_plan")

"""Release gate for the structured tag relation contract.

``Expense.tags`` is still kept as a small denormalised API/display field for
backward compatibility. Querying, stats, filtering, and future scale-sensitive
paths must be backed by ``tags`` + ``expense_tags`` relation rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (BACKEND_ROOT / path).read_text(encoding="utf-8")


def _fail(message: str) -> None:
    print(f"FAIL: {message}")


def _contains_all(path: str, tokens: tuple[str, ...]) -> list[str]:
    text = _read(path)
    return [token for token in tokens if token not in text]


def main() -> int:
    ok = True

    model_missing = _contains_all(
        "app/models/catalog.py",
        (
            "class Tag",
            "class ExpenseTag",
            "uq_tags_tenant_key",
            "uq_expense_tags_tenant_expense_tag",
            "fk_expense_tags_expense_tenant",
            "fk_expense_tags_tag_tenant",
            # Indexes are defined on the ORM model (create_all materialises them);
            # the legacy SQLite migrator that used to also declare them is retired.
            "ix_tags_tenant_key",
            "ix_expense_tags_tenant_expense",
            "ix_expense_tags_tenant_tag",
        ),
    )
    if model_missing:
        ok = False
        _fail("structured tag models/constraints/indexes missing: " + ", ".join(model_missing))

    sync_paths = (
        "app/services/expense_service/_create.py",
        "app/services/expense_service/_update.py",
        "app/services/import_service.py",
        "app/services/csv_import_batch_service/_apply.py",
    )
    for path in sync_paths:
        if "sync_expense_tags" not in _read(path):
            ok = False
            _fail(f"{path} no longer syncs expense_tags relation rows")

    test_missing = _contains_all(
        "tests/test_tags.py",
        (
            "test_manual_tags_normalize_filter_export_and_stats",
            "test_tag_filters_are_ledger_scoped",
            "test_import_rows_syncs_tag_relation_rows",
        ),
    )
    if test_missing:
        ok = False
        _fail("tag relation regression tests missing: " + ", ".join(test_missing))

    if ok:
        print("PASS: structured tag relation contract is enforced")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

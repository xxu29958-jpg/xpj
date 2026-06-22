"""Issue #65 slice 2: keep expense-by-id resolution funnelled through resolve_expense.

After slice 2 a single-row expense fetch by id goes through
``app.services.expense_query.resolve_expense`` (which handles a server id OR a
device-local ``local:{client_ref}`` ref), NOT a scattered
``ledger_scoped_select(Expense, …).where(Expense.id == expense_id)``. This lane fails
if that pattern reappears anywhere under ``backend/app`` — a new scattered lookup
silently bypasses the local-ref resolution path slice 3 depends on (it would only ever
match a server id, never ``local:{client_ref}``).

Intentionally NOT matched (different shapes, legitimately not full-row-by-id resolution):
projections (``ledger_scoped_select(...).with_only_columns(...).where(...)``), the
undo-reject CAS ``update(Expense).where(...)``, the bill-split
``select(Expense)...with_for_update()`` parent lock, table joins
(``Expense.id == <Other>.subject_id``), and foreign-key lookups
(``Expense.id == <row>.duplicate_of_id``). ``resolve_expense`` itself reads
``Expense.id == int(ref)`` (generic param, not ``expense_id``), so it is not flagged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# The full-row resolve pattern: ``.where`` directly follows the
# ``ledger_scoped_select(Expense, <tenant>)`` close-paren. A projection's
# ``.with_only_columns(...)`` between the two breaks the adjacency, so projections
# (and the update/select/join/foreign-key forms) do not match. DOTALL lets a single
# call span lines.
_SCATTERED_RESOLVE = re.compile(
    r"ledger_scoped_select\(\s*Expense\s*,[^)]*\)\s*\.where\(\s*Expense\.id\s*==\s*expense_id\s*\)",
    re.DOTALL,
)


def find_violations(source: str) -> list[str]:
    """Matched scattered-resolve snippets in ``source`` (empty list = clean)."""
    return _SCATTERED_RESOLVE.findall(source)


def _scan() -> list[str]:
    failures: list[str] = []
    for path in sorted(_APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if find_violations(path.read_text(encoding="utf-8")):
            failures.append(str(path.relative_to(_APP_ROOT.parent)).replace("\\", "/"))
    return failures


def main() -> int:
    failures = _scan()
    print("Expense-by-id resolution funnels through resolve_expense (issue #65 slice 2):")
    if failures:
        for rel in failures:
            print(
                "  FAIL  scattered ledger_scoped_select(Expense, …)"
                f".where(Expense.id == expense_id) in {rel}"
            )
        print(
            "        → use resolve_expense(db, tenant_id, expense_id) "
            "(app/services/expense_query.py)"
        )
    else:
        print("  OK  no scattered expense-by-id lookups outside resolve_expense")
    ok = not failures
    print(f"\n{'PASS' if ok else 'FAIL'}  expense-resolve")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

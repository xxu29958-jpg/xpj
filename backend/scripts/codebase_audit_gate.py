"""Known-debt gate for ``_audit_codebase.py``.

The audit script still prints the detailed report. This helper only
turns selected counters into a hard gate: current debt is allowed, new
debt fails, and improvements ask the developer to lower the baseline.
"""

from __future__ import annotations

DebtCounts = dict[str, int]

# Re-baselined for the v1.1 working tree (AI budget advisor + auth/migration
# hardening + this round's review fixes). ``files_over_500`` rose to 12 because
# the heavily-refactored ``background_task_service`` and the tenant-isolation
# tests in ``test_background_tasks`` legitimately grew past 500 — splitting
# cohesive files purely to stay under the line is the wrong trade. The lowered
# counters (nested_dict_args / service_public_no_private / unreferenced_modules)
# bank real reductions so they cannot silently regress later.
#
# ``route_layer_imports`` and ``mixed_return_functions`` are now 0: the audit
# was de-noised (route lane no longer counts the ``get_db`` DI import; the
# mixed-return lane skips declared Optionals and no longer attributes a nested
# closure's bare return to its parent), and the few genuine cases were moved
# into services (device_public_id / active_ledger_name) or behind TYPE_CHECKING.
# Both at 0 means any real route→model import or implicit-None return now fails.
CODEBASE_DEBT_LIMITS: DebtCounts = {
    "files_over_500": 12,
    "long_functions": 42,
    "deep_nesting_functions": 6,
    "route_layer_imports": 0,
    "service_public_no_private": 4,
    "global_usage": 6,
    "cached_singletons": 3,
    "nested_dict_args": 17,
    "mixed_return_functions": 0,
    "broad_exception": 24,
    "generic_raises": 7,
    "todo_markers": 9,
    "hardcoded_urls": 10,
    "credentials_risk": 4,
    "n_plus_one": 2,
    "unreferenced_modules": 218,
    "import_cycles": 0,
    "sql_outside_database": 0,
    "import_star": 0,
    "smelly_names": 0,
    "unannotated_long_functions": 0,
    "bare_except": 0,
    "swallowed_exceptions": 0,
    "hardcoded_paths": 0,
    "magic_numbers": 0,
}


def evaluate_debt(counts: DebtCounts) -> int:
    missing = sorted(set(CODEBASE_DEBT_LIMITS) - set(counts))
    regressions = [
        (key, counts[key], CODEBASE_DEBT_LIMITS[key])
        for key in sorted(CODEBASE_DEBT_LIMITS)
        if key in counts and counts[key] > CODEBASE_DEBT_LIMITS[key]
    ]
    improvements = [
        (key, counts[key], CODEBASE_DEBT_LIMITS[key])
        for key in sorted(CODEBASE_DEBT_LIMITS)
        if key in counts and counts[key] < CODEBASE_DEBT_LIMITS[key]
    ]

    print("== Gate. Known-debt baseline ==")
    if missing:
        print("FAIL: configured codebase debt counters were not reported:")
        for key in missing:
            print(f"  - {key}")
    if regressions:
        print("FAIL: codebase debt increased beyond the checked-in baseline:")
        for key, actual, limit in regressions:
            print(f"  - {key}: actual={actual}, allowed={limit}")
    if improvements:
        print("INFO: debt improved; lower CODEBASE_DEBT_LIMITS in this script:")
        for key, actual, limit in improvements:
            print(f"  - {key}: actual={actual}, old_limit={limit}")
    if not missing and not regressions:
        print(f"OK: {len(CODEBASE_DEBT_LIMITS)} counters at or below baseline.")
    print()
    return 1 if missing or regressions else 0

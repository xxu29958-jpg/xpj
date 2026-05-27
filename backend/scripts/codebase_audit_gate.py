"""Known-debt gate for ``_audit_codebase.py``.

The audit script still prints the detailed report. This helper only
turns selected counters into a hard gate: current debt is allowed, new
debt fails, and improvements ask the developer to lower the baseline.
"""

from __future__ import annotations

DebtCounts = dict[str, int]

CODEBASE_DEBT_LIMITS: DebtCounts = {
    "files_over_500": 10,
    "long_functions": 42,
    "deep_nesting_functions": 6,
    "route_layer_imports": 64,
    "service_public_no_private": 6,
    "global_usage": 6,
    "cached_singletons": 3,
    "nested_dict_args": 19,
    "mixed_return_functions": 91,
    "broad_exception": 24,
    "generic_raises": 7,
    "todo_markers": 9,
    "hardcoded_urls": 10,
    "credentials_risk": 4,
    "n_plus_one": 2,
    "unreferenced_modules": 225,
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

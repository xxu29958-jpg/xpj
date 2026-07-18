"""Audit strict PR-delta metrics with concrete product risk.

This lane reconciles mutate-token coverage against the checked-in strict
baseline. Test completeness belongs to the test runners themselves: fixed
collection roots, resource isolation, execution outcomes, and release
qualification prove that risk without freezing pytest counts or node ids.
"""

from __future__ import annotations

import pathlib
import sys
from collections import Counter

_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_BACKEND_ROOT = _SCRIPTS_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from _audit_mutate_token_coverage import (  # noqa: E402
    _iter_routes,
    _load_openapi_app_schema,
    _operation_carries_token,
)
from _mutate_token_ledger import ALLOWLIST, REASON_CODES  # noqa: E402
from codebase_audit_gate import evaluate_pr_delta_metrics  # noqa: E402


def _count_mutate_token_metrics() -> dict[str, int]:
    spec = _load_openapi_app_schema()
    routes = _iter_routes(spec)
    carriers = sum(
        1
        for method, path, operation in routes
        if f"{method} {path}" not in ALLOWLIST
        and _operation_carries_token(spec, operation)
    )
    reason_counter: Counter[str] = Counter(
        entry.reason_code for entry in ALLOWLIST.values()
    )
    counts = {
        "mutate_token_carriers": carriers,
        "mutate_token_exempted": len(ALLOWLIST),
    }
    counts.update(
        {
            f"mutate_token_reason_{code}": reason_counter.get(code, 0)
            for code in sorted(REASON_CODES)
        }
    )
    return counts


def main() -> int:
    print("== PR-delta verification ==")
    print()
    counts = _count_mutate_token_metrics()
    print("Actuals:")
    for key, value in sorted(counts.items()):
        print(f"  {key:50} {value:6d}")
    print()
    return evaluate_pr_delta_metrics(counts)


if __name__ == "__main__":
    raise SystemExit(main())

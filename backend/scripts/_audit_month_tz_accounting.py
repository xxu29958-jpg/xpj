"""Read-only audit: 'current month' must use the accounting timezone, not UTC.

The project's accounting timezone is Asia/Shanghai (``spending_contract_service.
accounting_timezone_key``). Deriving a month label (``%Y-%m``) or ``.month``
*directly from a UTC ``now``* — ``now_utc().month`` / ``now_utc().strftime(
"%Y-%m")`` / ``datetime.now(UTC).strftime("%Y-%m")`` — silently misplaces every
expense recorded in the few UTC-vs-Shanghai boundary hours into the wrong month.
This regression class has bitten month-boundary stats ~4 times.

The correct form threads the accounting tz: ``current_month(tz)`` /
``local_month_label(value, tz)`` (both in ``time_service``), or any
``<utc>.astimezone(<zone>)`` *before* taking ``.month`` / ``%Y-%m``.

This lane walks the AST and flags a ``now``-expression (``now_utc()`` /
``datetime.now(...)`` / ``datetime.utcnow()``) whose ``.month`` is taken, or
whose ``.strftime(...)`` format is exactly a year-month label (no day/time
fields), with NO ``.astimezone(...)`` between the ``now`` and the access.
Because the canonical helpers receive the tz as a parameter (so the ``now`` is
already localized via ``.astimezone``), they are not flagged — except
``time_service`` itself, which IS the helper and is allowlisted.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_month_tz_accounting.py

Exit 0 if all checks pass, 1 otherwise.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

APP_DIR = pathlib.Path("app")

# Calls that return a *UTC* now. ``.month`` / year-month ``.strftime`` taken off
# one of these, with no intervening ``.astimezone(...)``, is the bug.
_NOW_FUNCS = ("now_utc", "now", "utcnow")

# A format string that is *only* a year-month label (any separator / order),
# with NO day or sub-day field. ``%Y%m%d-%H%M%S`` (filename stamp) has %d → not
# matched; ``%Y-%m`` / ``%Y%m`` / ``%m/%Y`` → matched.
_MONTH_ONLY_FMT = re.compile(r"^[^%]*%Y[^%]*%m[^%]*$|^[^%]*%m[^%]*%Y[^%]*$")
_DAY_OR_TIME_FIELD = re.compile(r"%[djHMSpILUWwyfzZcxX]")

# Single documented exception: the canonical helper itself does
# ``now_utc().astimezone(safe_zone(tz)).strftime("%Y-%m")`` with a passed-in tz.
ALLOWLIST = ("app/services/time_service.py",)


def _is_now_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _NOW_FUNCS
    if isinstance(func, ast.Attribute):  # datetime.now(...) / datetime.utcnow()
        return func.attr in _NOW_FUNCS
    return False


def _astimezone_in_chain(node: ast.AST) -> bool:
    """True if ``.astimezone(...)`` appears anywhere below this attribute access."""
    cur = node
    while True:
        if isinstance(cur, ast.Call):
            f = cur.func
            if isinstance(f, ast.Attribute) and f.attr == "astimezone":
                return True
            cur = cur.func
        elif isinstance(cur, ast.Attribute):
            cur = cur.value
        else:
            return False


def _root_is_now(node: ast.AST) -> bool:
    """Walk down the attribute/call chain; True if its root is a UTC-now call."""
    cur = node
    while True:
        if _is_now_call(cur):
            return True
        if isinstance(cur, ast.Attribute):
            cur = cur.value
        elif isinstance(cur, ast.Call):
            cur = cur.func
        else:
            return False


def _month_only_strftime_fmt(node: ast.Call) -> str | None:
    f = node.func
    if not (isinstance(f, ast.Attribute) and f.attr == "strftime"):
        return None
    if not (node.args and isinstance(node.args[0], ast.Constant)):
        return None
    fmt = node.args[0].value
    if not isinstance(fmt, str):
        return None
    if _DAY_OR_TIME_FIELD.search(fmt):  # has %d/%H/... → not a month label
        return None
    return fmt if _MONTH_ONLY_FMT.match(fmt) else None


def _hits(path: pathlib.Path, tree: ast.AST) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        # case 1: <now-chain>.month  (no .astimezone between)
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "month"
            and _root_is_now(node.value)
            and not _astimezone_in_chain(node.value)
        ):
            out.append(
                f"{path.as_posix()}:{node.lineno} `.month` taken off a UTC now "
                f"with no .astimezone(accounting tz) — use current_month(tz) / "
                f"local_month_label(value, tz)"
            )
            continue
        # case 2: <now-chain>.strftime("%Y-%m")  (no .astimezone between)
        if isinstance(node, ast.Call):
            fmt = _month_only_strftime_fmt(node)
            if (
                fmt is not None
                and _root_is_now(node.func)
                and not _astimezone_in_chain(node.func)
            ):
                out.append(
                    f"{path.as_posix()}:{node.lineno} year-month strftime({fmt!r}) "
                    f"off a UTC now with no .astimezone(accounting tz) — use "
                    f"current_month(tz) / local_month_label(value, tz)"
                )
    return out


def main() -> int:
    failures: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if any(path.as_posix().endswith(a) for a in ALLOWLIST):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        failures.extend(_hits(path, tree))

    print("Current-month label uses accounting timezone (not UTC):")
    if failures:
        for line in failures:
            print(f"  FAIL  {line}")
    else:
        print("  OK  no UTC-now month label without .astimezone(accounting tz)")
    ok = not failures
    print(f"\n{'PASS' if ok else 'FAIL'}  month-tz-accounting")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

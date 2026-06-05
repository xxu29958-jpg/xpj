"""Read-only audit: 'current month' must use the accounting timezone, not UTC.

The project's accounting timezone is Asia/Shanghai (``spending_contract_service.
accounting_timezone_key``). Deriving a month label (``%Y-%m``) or ``.month``
*from a UTC ``now``* — ``now_utc().month`` / ``now_utc().strftime("%Y-%m")`` /
``datetime.now(UTC).strftime("%Y-%m")`` — silently misplaces every expense
recorded in the few UTC-vs-Shanghai boundary hours into the wrong month. This
regression class has bitten month-boundary stats ~4 times.

The correct form threads the accounting tz: ``current_month(tz)`` /
``local_month_label(value, tz)`` (both in ``time_service``), or any
``<utc>.astimezone(<zone>)`` *before* taking ``.month`` / ``%Y-%m``.

This lane walks the AST and flags ``.month`` / a year-month ``.strftime(...)`` /
a year-month f-string ``format_spec`` whose root is a UTC now — taken directly
(``now_utc().month``), through a local variable holding a raw UTC now
(``m = now_utc(); m.month``), or through a same-file zero-/any-arg helper that
returns a raw UTC now (``def _now(): return now_utc()`` then ``_now().month``) —
with NO ``.astimezone(...)`` between the now and the access. The canonical
helpers thread the tz as a parameter (so the now is already localized via
``.astimezone``) and are not flagged; ``time_service`` IS the helper and is
allowlisted.

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
# one of these (directly, via a raw-now local var, or via a now-returning helper),
# with no intervening ``.astimezone(...)``, is the bug.
_NOW_FUNCS = ("now_utc", "now", "utcnow")

# A format string that is *only* a year-month label (any separator / order),
# with NO day or sub-day field. ``%Y%m%d-%H%M%S`` (filename stamp) has %d → not
# matched; ``%Y-%m`` / ``%Y%m`` / ``%m/%Y`` → matched.
_MONTH_ONLY_FMT = re.compile(r"^[^%]*%Y[^%]*%m[^%]*$|^[^%]*%m[^%]*%Y[^%]*$")
_DAY_OR_TIME_FIELD = re.compile(r"%[djHMSpILUWwyfzZcxX]")

# Single documented exception: the canonical helper itself does
# ``now_utc().astimezone(safe_zone(tz)).strftime("%Y-%m")`` with a passed-in tz.
ALLOWLIST = ("app/services/time_service.py",)

_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_EMPTY: frozenset[str] = frozenset()


def _is_now_call(node: ast.AST, aliases: frozenset[str] = _EMPTY) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _NOW_FUNCS or func.id in aliases
    if isinstance(func, ast.Attribute):  # datetime.now(...) / datetime.utcnow()
        return func.attr in _NOW_FUNCS
    return False


def _astimezone_in_chain(node: ast.AST) -> bool:
    """True if ``.astimezone(...)`` appears anywhere below this access."""
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


def _root_now_or_tainted(
    node: ast.AST, tainted: frozenset[str], aliases: frozenset[str] = _EMPTY
) -> bool:
    """Walk the attribute/call chain; True if its root is a UTC-now call (incl. a
    now-returning helper) or a local name holding a raw UTC now (``tainted``)."""
    cur = node
    while True:
        if _is_now_call(cur, aliases):
            return True
        if isinstance(cur, ast.Name):
            return cur.id in tainted
        if isinstance(cur, ast.Attribute):
            cur = cur.value
        elif isinstance(cur, ast.Call):
            cur = cur.func
        else:
            return False


def _iter_scope(scope: ast.AST):
    """Yield nodes lexically in ``scope``, NOT descending into nested
    function / lambda bodies, so taint and accesses stay per-scope."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _NESTED_SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _assignment_target_and_value(node: ast.AST):
    if isinstance(node, ast.Assign):
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        return names, node.value
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is not None
    ):
        return [node.target.id], node.value
    if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):  # walrus
        return [node.target.id], node.value
    return [], None


def _tainted_names(scope: ast.AST, aliases: frozenset[str] = _EMPTY) -> frozenset[str]:
    """Names whose *every* assignment in this scope is a raw UTC now (now-rooted,
    no ``.astimezone``) — i.e. the name holds a raw UTC instant. A name ever
    assigned anything else (incl. a localized value) is NOT tainted, so the
    rescue ``m = now_utc(); m = m.astimezone(tz); m.month`` is not flagged."""
    raw: set[str] = set()
    other: set[str] = set()
    for node in _iter_scope(scope):
        names, value = _assignment_target_and_value(node)
        if not names:
            continue
        is_raw_now = _root_now_or_tainted(value, _EMPTY, aliases) and not _astimezone_in_chain(value)
        for name in names:
            (raw if is_raw_now else other).add(name)
    return frozenset(raw - other)


def _collect_now_aliases(tree: ast.AST) -> frozenset[str]:
    """Names of same-file helpers whose *every* ``return`` yields a raw UTC now
    (now-rooted, no ``.astimezone``) — calling such a helper is itself a raw now.
    Intra-file only; one level (helper → ``now_utc()``), no cross-module chase."""
    aliases: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        returns = [
            n for n in _iter_scope(fn) if isinstance(n, ast.Return) and n.value is not None
        ]
        if returns and all(
            _root_now_or_tainted(r.value, _tainted_names(fn)) and not _astimezone_in_chain(r.value)
            for r in returns
        ):
            aliases.add(fn.name)
    return frozenset(aliases)


def _month_only_strftime_fmt(node: ast.Call) -> str | None:
    f = node.func
    if not (isinstance(f, ast.Attribute) and f.attr == "strftime"):
        return None
    if not (node.args and isinstance(node.args[0], ast.Constant)):
        return None
    return _classify_month_fmt(node.args[0].value)


def _fstring_month_spec(node: ast.FormattedValue) -> str | None:
    spec = node.format_spec
    if not isinstance(spec, ast.JoinedStr):
        return None
    parts: list[str] = []
    for piece in spec.values:
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
            parts.append(piece.value)
        else:
            return None  # dynamic format spec — skip
    return _classify_month_fmt("".join(parts))


def _classify_month_fmt(fmt: object) -> str | None:
    if not isinstance(fmt, str) or not fmt:
        return None
    if _DAY_OR_TIME_FIELD.search(fmt):  # has %d/%H/... → not a month label
        return None
    return fmt if _MONTH_ONLY_FMT.match(fmt) else None


def _hits(path: pathlib.Path, tree: ast.AST) -> list[str]:
    out: list[str] = []
    aliases = _collect_now_aliases(tree)
    scopes: list[ast.AST] = [tree]
    scopes += [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    advice = (
        "use current_month(tz) / local_month_label(value, tz), or "
        ".astimezone(accounting tz) before the access"
    )
    for scope in scopes:
        tainted = _tainted_names(scope, aliases)
        for node in _iter_scope(scope):
            # case 1: <now-or-raw-now-var-or-now-helper>.month  (no .astimezone)
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "month"
                and _root_now_or_tainted(node.value, tainted, aliases)
                and not _astimezone_in_chain(node.value)
            ):
                out.append(f"{path.as_posix()}:{node.lineno} `.month` off a UTC now — {advice}")
                continue
            # case 2: <...>.strftime("%Y-%m")
            if isinstance(node, ast.Call):
                fmt = _month_only_strftime_fmt(node)
                if (
                    fmt is not None
                    and _root_now_or_tainted(node.func, tainted, aliases)
                    and not _astimezone_in_chain(node.func)
                ):
                    out.append(
                        f"{path.as_posix()}:{node.lineno} year-month strftime({fmt!r}) "
                        f"off a UTC now — {advice}"
                    )
                    continue
            # case 3: f-string  f"{<...>:%Y-%m}"
            if isinstance(node, ast.FormattedValue):
                fmt = _fstring_month_spec(node)
                if (
                    fmt is not None
                    and _root_now_or_tainted(node.value, tainted, aliases)
                    and not _astimezone_in_chain(node.value)
                ):
                    out.append(
                        f"{path.as_posix()}:{node.lineno} year-month f-string "
                        f"format_spec({fmt!r}) off a UTC now — {advice}"
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

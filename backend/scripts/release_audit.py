"""Release-time audit aggregator.

Auto-discovers every ``_audit_*.py`` in this directory and runs them
in sequence, printing a consolidated PASS / FAIL summary. There is
no opt-in step: drop a new audit script next to this one and it is
already gated by CI (this script is wired into the backend-full job in
``.gitea/workflows/windows-ci.yml``) and by ``verify_project.ps1``.

"PASS" here means **no new regressions outside each lane's
allowlist** — it does NOT mean "no architectural debt". Known v0.9
service cycles are tracked in ``_audit_service_graph.py::KNOWN_CYCLES``
and printed as ``(known)`` rather than failing the audit. Fix the
cycle, or — if it's not on this release's critical path — add it to
the allowlist with the ticket/commit that introduced it. New cycles
outside the allowlist DO fail the audit.

What each lane catches (from the v1.0 maturity-audit lessons):

- ``_audit_service_graph.py``  — service-to-service import graph +
  cycles. Catches the kind of cycle that hid
  ``expense_service ↔ receipt_item_service`` until v1.0.

- ``_audit_codebase.py``       — 7-dimension codebase audit
  (file LOC, surface area, **long functions**, nesting, layer
  violations, ...). The long-functions section catches the kind of
  120-line route handler that ``web_review_bulk`` had.

- ``_audit_ci_gap.py``         — required gradle tasks / pytest
  lanes are actually invoked by CI. Catches the kind of gap that hid
  ``connectedGrayDebugAndroidTest`` (task existed, CI never ran it).

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/release_audit.py

Exit code 0 if every lane passes, non-zero if any lane fails. Output
is human-readable; the per-lane reports are unmodified so you can
spot-check the actual symptoms.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

_REQUIRED_LANE_CALLS: dict[str, frozenset[str]] = {
    "_audit_pr_delta_metrics.py": frozenset(
        {
            "evaluate_pr_delta_metrics",
            "evaluate_protected_pytest_memberships",
        }
    ),
}


def _configure_utf8_stdio() -> None:
    # Windows CI runs Python with cp1252 stdout by default; audit output
    # contains Chinese identifiers and string literals from source code,
    # so charmap blows up mid-print. Force UTF-8 here so every spawned
    # subprocess inherits it via PYTHONIOENCODING.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _discover_lanes(scripts_dir: Path) -> list[tuple[str, str]]:
    """Every ``_audit_*.py`` in this directory is a lane, no opt-in step.

    Naming convention: ``_audit_<label-with-underscores>.py`` →
    label ``<label-with-dashes>``. Dropping a new audit script in
    place picks it up automatically — no edit to this file, no edit
    to ci.yml, no "remember to add it to LANES" footgun.

    The leading underscore signals "private / single-purpose
    script, not an importable module"; ``_audit_codebase.py`` lives
    by the same convention. Files prefixed ``_audit_wip_`` are
    skipped so an in-flight audit doesn't gate PRs before it's
    ready.
    """
    lanes: list[tuple[str, str]] = []
    for path in sorted(scripts_dir.glob("_audit_*.py")):
        stem = path.stem  # e.g. "_audit_service_graph"
        if stem.startswith("_audit_wip_"):
            continue
        label = stem.removeprefix("_audit_").replace("_", "-")
        lanes.append((label, path.name))
    return lanes


def _call_name(call: ast.Call) -> str | None:
    return call.func.id if isinstance(call.func, ast.Name) else None


def _statement_call_name(statement: ast.stmt) -> str | None:
    expression: ast.expr | None = None
    if isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign, ast.Return)):
        expression = statement.value
    return _call_name(expression) if isinstance(expression, ast.Call) else None


def _expression_directly_calls_main(expression: ast.expr) -> bool:
    if not isinstance(expression, ast.Call):
        return False
    if _call_name(expression) == "main":
        return True
    return any(
        isinstance(argument, ast.Call) and _call_name(argument) == "main"
        for argument in expression.args
    )


def _module_executes_main(module: ast.Module) -> bool:
    for statement in module.body:
        if not isinstance(statement, ast.If):
            continue
        comparison = statement.test
        if not (
            isinstance(comparison, ast.Compare)
            and isinstance(comparison.left, ast.Name)
            and comparison.left.id == "__name__"
            and len(comparison.ops) == 1
            and isinstance(comparison.ops[0], ast.Eq)
            and len(comparison.comparators) == 1
            and isinstance(comparison.comparators[0], ast.Constant)
            and comparison.comparators[0].value == "__main__"
        ):
            continue
        return any(
            isinstance(child, ast.Expr)
            and _expression_directly_calls_main(child.value)
            for child in statement.body
        )
    return False


def _required_lane_contract_failures(
    scripts_dir: Path,
    lanes: list[tuple[str, str]],
) -> list[str]:
    discovered = {filename for _label, filename in lanes}
    failures: list[str] = []
    for filename, required_calls in _REQUIRED_LANE_CALLS.items():
        if filename not in discovered:
            failures.append(f"required release audit lane is missing or excluded: {filename}")
            continue
        path = scripts_dir / filename
        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=filename)
        except (OSError, SyntaxError, UnicodeError) as exc:
            failures.append(f"required release audit lane is unreadable: {filename}: {exc}")
            continue
        main_functions = [
            node
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
        ]
        if len(main_functions) != 1:
            failures.append(f"required release audit lane must define exactly one main(): {filename}")
            continue
        called = {
            name
            for statement in main_functions[0].body
            if (name := _statement_call_name(statement)) is not None
        }
        for missing_call in sorted(required_calls - called):
            failures.append(f"required release audit call is missing: {filename}: {missing_call}")
        if not _module_executes_main(module):
            failures.append(f"required release audit lane does not execute main(): {filename}")
    return failures


def _compact_output_enabled() -> bool:
    return os.environ.get("XPJ_RELEASE_AUDIT_COMPACT") == "1"


def _run_lane(label: str, filename: str, scripts_dir: Path, *, compact: bool) -> bool:
    script = scripts_dir / filename
    if not compact:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=scripts_dir.parent,
        )
        return result.returncode == 0

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=scripts_dir.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ok = result.returncode == 0
    if ok:
        print(f"PASS  {label}")
        return True

    print(f"FAIL  {label}")
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return False


def main() -> int:
    _configure_utf8_stdio()
    scripts_dir = Path(__file__).resolve().parent
    lanes = _discover_lanes(scripts_dir)
    required_lane_failures = _required_lane_contract_failures(scripts_dir, lanes)
    if required_lane_failures:
        print("RELEASE AUDIT: required lane contract failed")
        for failure in required_lane_failures:
            print(f"  - {failure}")
        return 1
    if not lanes:
        print("RELEASE AUDIT: no _audit_*.py scripts found — nothing to run")
        return 1

    overall_ok = True
    summary: list[tuple[str, bool]] = []
    compact = _compact_output_enabled()

    for label, filename in lanes:
        print("=" * 78)
        print(f"AUDIT LANE: {label} ({filename})")
        print("=" * 78)
        sys.stdout.flush()
        ok = _run_lane(label, filename, scripts_dir, compact=compact)
        summary.append((label, ok))
        if not ok:
            overall_ok = False
        print()

    print("=" * 78)
    print("RELEASE AUDIT SUMMARY")
    print("=" * 78)
    for label, ok in summary:
        marker = "PASS" if ok else "FAIL"
        print(f"  {marker}  {label}")
    print()
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())

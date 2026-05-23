"""Release-time audit aggregator.

Runs the three read-only audits in sequence and prints a consolidated
PASS / FAIL summary. Manual — invoke before cutting a release
candidate (or anytime you want a snapshot of the slow-rotting parts).

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

import subprocess
import sys
from pathlib import Path

LANES: list[tuple[str, str]] = [
    ("service-graph", "_audit_service_graph.py"),
    ("codebase", "_audit_codebase.py"),
    ("ci-gap", "_audit_ci_gap.py"),
]


def main() -> int:
    scripts_dir = Path(__file__).resolve().parent
    overall_ok = True
    summary: list[tuple[str, bool]] = []

    for label, filename in LANES:
        script = scripts_dir / filename
        print("=" * 78)
        print(f"AUDIT LANE: {label} ({filename})")
        print("=" * 78)
        sys.stdout.flush()
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=Path.cwd(),
        )
        ok = result.returncode == 0
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

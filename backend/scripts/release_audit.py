"""Release-time audit aggregator.

Auto-discovers every ``_audit_*.py`` in this directory and runs them
in sequence, printing a consolidated PASS / FAIL summary. There is
no opt-in step: drop a new audit script next to this one and it is
already gated by CI (this script is wired into the Backend job in
``.github/workflows/ci.yml``) and by ``verify_project.ps1``.

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

import os
import subprocess
import sys
from pathlib import Path

# Windows CI runs Python with cp1252 stdout by default; audit output
# contains Chinese identifiers and string literals from source code,
# so charmap blows up mid-print. Force UTF-8 here so every spawned
# subprocess inherits it via PYTHONIOENCODING.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
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


def main() -> int:
    scripts_dir = Path(__file__).resolve().parent
    lanes = _discover_lanes(scripts_dir)
    if not lanes:
        print("RELEASE AUDIT: no _audit_*.py scripts found — nothing to run")
        return 1

    overall_ok = True
    summary: list[tuple[str, bool]] = []

    for label, filename in lanes:
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

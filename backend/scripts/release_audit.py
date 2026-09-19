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

- ``_audit_codebase.py``       — Backend Python 7-dimension audit
  (file LOC, surface area, **long functions**, nesting, layer
  violations, ...). The long-functions section catches the kind of
  120-line route handler that ``web_review_bulk`` had.

- ``_audit_repository_weight.py`` — immutable whole-repository LOC,
  module/language/role breakdown and measured debt delta. LOC is a trend;
  size, native/recorded complexity and suppression debt cannot grow.

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

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_REQUIRED_LANES = frozenset(
    {
        ("pr-delta-metrics", "_audit_pr_delta_metrics.py"),
        ("repository-weight", "_audit_repository_weight.py"),
    }
)


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
    missing = _REQUIRED_LANES.difference(lanes)
    if missing:
        details = ", ".join(filename for _label, filename in sorted(missing))
        raise RuntimeError(f"required release audit lane is missing: {details}")
    return lanes


def _compact_output_enabled() -> bool:
    return os.environ.get("XPJ_RELEASE_AUDIT_COMPACT") == "1"


def _run_lane(label: str, filename: str, scripts_dir: Path, *, compact: bool) -> int | None:
    script = scripts_dir / filename
    try:
        if not compact:
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=scripts_dir.parent,
            )
            return result.returncode
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=scripts_dir.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    if result.returncode == 0:
        print(f"PASS  {label}")
        return result.returncode
    print(f"FAIL  {label}")
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def _lane_timing_record(
    *,
    label: str,
    filename: str,
    returncode: int | None,
    started_utc: str,
    ended_utc: str,
    elapsed_s: float,
) -> dict[str, object]:
    return {
        "lane": label,
        "filename": filename,
        "returncode": returncode,
        "started_utc": started_utc,
        "ended_utc": ended_utc,
        "elapsed_s": round(elapsed_s, 3),
        "elapsed_clock": "monotonic",
        "measurement_kind": "direct",
        "complete": returncode is not None,
    }


def main() -> int:
    _configure_utf8_stdio()
    scripts_dir = Path(__file__).resolve().parent
    lanes = _discover_lanes(scripts_dir)
    if not lanes:
        print("RELEASE AUDIT: no _audit_*.py scripts found — nothing to run")
        return 1

    overall_ok = True
    summary: list[tuple[str, int | None]] = []
    compact = _compact_output_enabled()

    for label, filename in lanes:
        print("=" * 78)
        print(f"AUDIT LANE: {label} ({filename})")
        print("=" * 78)
        sys.stdout.flush()
        started = time.monotonic()
        started_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        returncode = _run_lane(label, filename, scripts_dir, compact=compact)
        elapsed = time.monotonic() - started
        ended_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        record = _lane_timing_record(
            label=label,
            filename=filename,
            returncode=returncode,
            started_utc=started_utc,
            ended_utc=ended_utc,
            elapsed_s=elapsed,
        )
        print("AUDIT_LANE_TIMING " + json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        summary.append((label, returncode))
        if returncode != 0:
            overall_ok = False
        print()

    expected = [label for label, _filename in lanes]
    completed = [label for label, returncode in summary if returncode is not None]
    run_complete = len(completed) == len(expected) and all(returncode is not None for _label, returncode in summary)
    print(
        "AUDIT_RUN_TIMING "
        + json.dumps(
            {
                "expected_lanes": expected,
                "expected_lane_count": len(expected),
                "completed_lane_count": len(completed),
                "overall_returncode": None if not run_complete else (0 if overall_ok else 1),
                "complete": run_complete,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    print("=" * 78)
    print("RELEASE AUDIT SUMMARY")
    print("=" * 78)
    for label, returncode in summary:
        marker = "PASS" if returncode == 0 else "FAIL"
        print(f"  {marker}  {label}")
    print()
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())

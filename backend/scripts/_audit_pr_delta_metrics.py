"""ADR-0038 prep: PR-Δ verification audit lane.

Separate lane from :mod:`_audit_codebase`: that one is a debt-counter
audit (one-direction drift — improvement OK, regression FAIL); this
lane uses **strict-equality** semantics on a different set of counters
(both directions FAIL, meaning either "you didn't update the baseline"
or "the actual didn't move as declared").

Cut-over PRs (ADR-0038's PR-A/B/C/D) declare their expected Δ by
bumping :data:`codebase_audit_gate.STRICT_EQUALITY_BASELINE` in the
same diff that changes actuals; CI verifies actual == baseline + Δ;
mismatch fails. The mechanism replaces the previous "PR description
says +8/-8, reviewer eyeballs it" pattern with machine reconciliation.

Auto-discovered by :file:`release_audit.py` (any ``_audit_*.py`` in
``backend/scripts/`` is a lane, no opt-in step).

What this lane counts
---------------------

- **mutate_token_carriers** — routes whose request body declares
  ``expected_updated_at`` or ``expected_updated_at_by_id``.
- **mutate_token_exempted** — routes in
  :data:`_mutate_token_ledger.ALLOWLIST`.
- **mutate_token_reason_<code>** — one counter per reason_code in
  ALLOWLIST. Catches PR-D's ``terminal_flag_flip`` split mechanically:
  the per-code distribution must match baseline; a missed
  reclassification shows up as a mismatch on the specific counter.
- **backend_pytest_count** — exact count from ``pytest --collect-only``
  (NOT regex; regex has built-in error tolerance that would defeat the
  precise-reconciliation purpose).

Android ``@Test`` count is checked separately by the Android CI lane
(``:app:verifyTestCountBaseline`` gradle task against
``android/audit/test_count_baseline.txt``). Cross-job coordination is
intentionally avoided — each side enforces its own contract.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_pr_delta_metrics.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from collections import Counter

# sys.path bootstrap so sibling scripts + ``app.*`` imports both resolve
# whether the script is run directly, via release_audit subprocess, or
# from an arbitrary cwd.
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_BACKEND_ROOT = _SCRIPTS_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Imported here to keep the helper definitions single-sourced. The
# leading underscores on the sibling's helpers are a Python convention,
# not a hard barrier — co-locating both audit lanes in
# ``backend/scripts/`` makes this coupling intentional and reviewable
# (drift between the two audits would be the symptom of someone editing
# one without the other, which is exactly what we want to surface).
from _audit_mutate_token_coverage import (  # noqa: E402 — sys.path bootstrap above
    _iter_routes,
    _load_openapi_app_schema,
    _operation_carries_token,
)
from _mutate_token_ledger import ALLOWLIST, REASON_CODES  # noqa: E402
from codebase_audit_gate import evaluate_pr_delta_metrics  # noqa: E402


def _count_mutate_token_metrics() -> dict[str, int]:
    """Compute carriers / exempted / per-reason-code distribution from the
    live OpenAPI schema and the checked-in ledger.

    Per-reason-code output uses the **full REASON_CODES vocabulary** with
    explicit 0 for reason_codes that no ALLOWLIST entry currently uses.
    This is critical: if a reason_code drops to 0 routes (e.g. PR-D moves
    all ``terminal_flag_flip`` routes to other codes), the output dict
    must STILL contain ``mutate_token_reason_terminal_flag_flip=0``, not
    omit the key. Omitting would let the gate's "missing key" check
    silently shift the failure mode (baseline still has the key at the
    old value, actual doesn't have it at all → caught as missing, but
    the message would be ambiguous). Explicit 0 keeps the comparison
    table shape constant and the gate semantics clean.
    """
    spec = _load_openapi_app_schema()
    routes = _iter_routes(spec)

    carriers = 0
    for method, path, operation in routes:
        key = f"{method} {path}"
        if key in ALLOWLIST:
            # Exempted routes aren't carriers even if their schema happens
            # to declare the field (allowlist_but_has_token failure mode
            # is owned by _audit_mutate_token_coverage; here we just count
            # what's exempted).
            continue
        if _operation_carries_token(spec, operation):
            carriers += 1

    exempted = len(ALLOWLIST)
    reason_counter: Counter[str] = Counter(entry.reason_code for entry in ALLOWLIST.values())

    out: dict[str, int] = {
        "mutate_token_carriers": carriers,
        "mutate_token_exempted": exempted,
    }
    # Emit ALL reason_codes including 0s — see docstring.
    for code in sorted(REASON_CODES):
        out[f"mutate_token_reason_{code}"] = reason_counter.get(code, 0)
    return out


def _count_backend_pytest_tests() -> int:
    """Exact pytest test count via ``pytest tests --collect-only``.

    NOT regex on ``def test_*``. Per ADR-0038 prep design: regex has
    built-in tolerance for parametrize / commented-out tests / multiline
    decorators that directly contradicts the precise-Δ-reconciliation
    purpose. ``--collect-only`` reports the actual collected test count
    (parametrized expansions included), which is what cut-over PRs
    declare deltas against.

    Explicit ``tests`` positional arg avoids relying on pyproject.toml's
    testpaths default — making the count semantic ("pytest collected
    under tests/") unambiguous and resilient to future config drift.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",  # Windows GBK default mangles Chinese in pytest warnings
        errors="replace",
        check=False,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`pytest tests --collect-only` failed (exit={result.returncode}).\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    # pytest -q summary line at the end: "N tests collected in M.MMs"
    # or "N tests collected, K errors in ..." on partial collection.
    for line in reversed(result.stdout.splitlines()):
        match = re.search(r"(\d+)\s+tests?\s+collected", line)
        if match:
            return int(match.group(1))
    raise RuntimeError(
        "could not parse `pytest --collect-only` output.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def main() -> int:
    """Producer + thin orchestration. All policy (which counters are
    strict-equality, which ratchet UP/DOWN, bootstrap exception) lives
    in the gate. This file is allowed to import gate's public
    ``evaluate_pr_delta_metrics`` API, but not its internals (baselines,
    ratchet sets, helpers) — that's the boundary that keeps producer
    pure-data and gate fully owning policy.
    """
    print("== ADR-0038 PR-Δ verification ==")
    print()

    counts: dict[str, int] = {}
    counts.update(_count_mutate_token_metrics())
    counts["backend_pytest_count"] = _count_backend_pytest_tests()

    print("Actuals:")
    for key, value in sorted(counts.items()):
        print(f"  {key:50} {value:6d}")
    print()

    return evaluate_pr_delta_metrics(counts)


if __name__ == "__main__":
    sys.exit(main())

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
  ``expected_row_version`` or ``expected_row_version_by_id``.
- **mutate_token_exempted** — routes in
  :data:`_mutate_token_ledger.ALLOWLIST`.
- **mutate_token_reason_<code>** — one counter per reason_code in
  ALLOWLIST. Catches PR-D's ``terminal_flag_flip`` split mechanically:
  the per-code distribution must match baseline; a missed
  reclassification shows up as a mismatch on the specific counter.
- **backend_pytest_count** — exact count from ``pytest --collect-only``.
- **backend_pytest_parallel_count**, **backend_pytest_real_db_count**, and
  **backend_pytest_stateful_count** record the explicit marker partition.
- **backend_pytest_*_membership_digest** records sorted SHA-256 fingerprints for
  ``real_db`` and ``stateful_serial``. The gate also protects exact-base backend,
  parallel, marker, and packaging memberships. A parallel test may leave that
  lane only by promotion into ``stateful_serial``.
- **installer_pytest_count** — exact count from the isolated Windows installer
  contract lane under ``packaging/tests``.

Android ``@Test`` count is checked separately by the Android CI lane
(``:app:assertAndroidTestCountEqualsBaseline`` gradle task against
``android/audit/test_count_baseline.txt``). Cross-job coordination is
intentionally avoided — each side enforces its own contract.

Run from ``backend/``::

    .venv/Scripts/python.exe scripts/_audit_pr_delta_metrics.py
"""

from __future__ import annotations

import io
import os
import pathlib
import subprocess
import sys
import tarfile
from collections import Counter
from collections.abc import Mapping
from tempfile import TemporaryDirectory

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
from adr_contract_git import (  # noqa: E402
    has_auditable_ci_context,
    select_ratchet_base,
)
from codebase_audit_gate import evaluate_pr_delta_metrics  # noqa: E402
from packaging_pytest_contract import (  # noqa: E402
    PACKAGING_PARALLEL_MARKER,
    PACKAGING_SERIAL_MARKER,
)
from pytest_execution_contract import (  # noqa: E402
    collect_pytest_snapshot,
    parse_pytest_collection,
    pytest_collection_command,
    pytest_execution_environment,
    pytest_nodeid_digest,
)
from pytest_membership_gate import evaluate_protected_pytest_memberships  # noqa: E402


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


def _pytest_collection_environment() -> dict[str, str]:
    return pytest_execution_environment()


def _pytest_collection_command(
    target: str,
    mark_expression: str | None,
) -> list[str]:
    return pytest_collection_command(target, mark_expression)


def _parse_pytest_collection(
    target: str,
    result: subprocess.CompletedProcess[str],
    *,
    allow_empty: bool,
) -> tuple[int, tuple[str, ...]]:
    snapshot = parse_pytest_collection(target, result, allow_empty=allow_empty)
    return snapshot.count, snapshot.nodeids


def _collect_pytest_tests(
    target: str,
    *,
    mark_expression: str | None = None,
    backend_root: pathlib.Path = _BACKEND_ROOT,
    allow_empty: bool = False,
) -> tuple[int, tuple[str, ...]]:
    """Collect exact pytest node ids from one explicit root and marker filter."""

    snapshot = collect_pytest_snapshot(
        target,
        mark_expression=mark_expression,
        backend_root=backend_root,
        allow_empty=allow_empty,
    )
    return snapshot.count, snapshot.nodeids


def _count_pytest_tests(
    target: str,
    *,
    mark_expression: str | None = None,
) -> int:
    return _collect_pytest_tests(
        target,
        mark_expression=mark_expression,
    )[0]


def _pytest_membership_digest(nodeids: tuple[str, ...]) -> int:
    return int(pytest_nodeid_digest(nodeids), 16)


def _extract_trusted_backend_snapshot(ref: str, destination: pathlib.Path) -> None:
    result = subprocess.run(
        ["git", "archive", "--format=tar", ref, "backend"],
        cwd=_BACKEND_ROOT.parent,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"git archive failed for {ref}: {stderr}")
    destination_root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            member_path = (destination / member.name).resolve()
            if (
                not member_path.is_relative_to(destination_root)
                or not (member.name == "backend" or member.name.startswith("backend/"))
                or not (member.isfile() or member.isdir())
            ):
                raise RuntimeError(f"base backend archive contains an unsafe member: {member.name!r}")
        archive.extractall(destination, members=members, filter="data")


def _collect_base_packaging_memberships(
    backend_root: pathlib.Path,
) -> dict[str, tuple[str, ...]]:
    complete = _collect_pytest_tests(
        "packaging/tests",
        backend_root=backend_root,
    )[1]
    conftest = backend_root / "packaging" / "tests" / "conftest.py"
    if not conftest.is_file() or "packaging_resource" not in conftest.read_text(
        encoding="utf-8"
    ):
        return {
            "packaging_all": complete,
            "packaging_parallel": (),
            "packaging_serial": (),
        }
    return {
        "packaging_all": complete,
        "packaging_parallel": _collect_pytest_tests(
            "packaging/tests",
            mark_expression=PACKAGING_PARALLEL_MARKER,
            backend_root=backend_root,
            allow_empty=True,
        )[1],
        "packaging_serial": _collect_pytest_tests(
            "packaging/tests",
            mark_expression=PACKAGING_SERIAL_MARKER,
            backend_root=backend_root,
            allow_empty=True,
        )[1],
    }


def _collect_base_pytest_memberships(
    environment: Mapping[str, str],
) -> tuple[bool, dict[str, tuple[str, ...]], bool, str | None]:
    environ = dict(environment)
    base_required = bool(environ.get("XPJ_AUDIT_BASE_REF", "").strip()) or (has_auditable_ci_context(environ))
    selected, selection_error = select_ratchet_base(_BACKEND_ROOT.parent, environ)
    if selected is None:
        return False, {}, base_required, selection_error
    try:
        with TemporaryDirectory(prefix="xpj-pytest-base-") as temporary:
            snapshot_root = pathlib.Path(temporary)
            _extract_trusted_backend_snapshot(selected.commit, snapshot_root)
            backend_root = snapshot_root / "backend"
            conftest_text = (backend_root / "tests" / "conftest.py").read_text(
                encoding="utf-8"
            )
            memberships = {
                "backend_all": _collect_pytest_tests(
                    "tests",
                    backend_root=backend_root,
                )[1],
                "backend_parallel": _collect_pytest_tests(
                    "tests",
                    mark_expression="not stateful_serial",
                    backend_root=backend_root,
                )[1],
                "parallel_safe": (
                    _collect_pytest_tests(
                        "tests",
                        mark_expression="parallel_safe",
                        backend_root=backend_root,
                        allow_empty=True,
                    )[1]
                    if "parallel_safe:" in conftest_text
                    else ()
                ),
                "real_db": _collect_pytest_tests(
                    "tests",
                    mark_expression="real_db",
                    backend_root=backend_root,
                    allow_empty=True,
                )[1],
                "stateful_serial": _collect_pytest_tests(
                    "tests",
                    mark_expression="stateful_serial",
                    backend_root=backend_root,
                    allow_empty=True,
                )[1],
                "cluster_serial": (
                    _collect_pytest_tests(
                        "tests",
                        mark_expression="cluster_serial",
                        backend_root=backend_root,
                        allow_empty=True,
                    )[1]
                    if "cluster_serial:" in conftest_text
                    else ()
                ),
                **_collect_base_packaging_memberships(backend_root),
            }
    except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as exc:
        return False, {}, base_required, f"{selected.ref}: {exc}"
    return True, memberships, base_required, None


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
    backend_count, backend_nodeids = _collect_pytest_tests("tests")
    counts["backend_pytest_count"] = backend_count
    parallel_count, parallel_nodeids = _collect_pytest_tests(
        "tests",
        mark_expression="not stateful_serial",
    )
    counts["backend_pytest_parallel_count"] = parallel_count
    parallel_safe_count, parallel_safe_nodeids = _collect_pytest_tests(
        "tests",
        mark_expression="parallel_safe",
    )
    counts["backend_pytest_parallel_safe_count"] = parallel_safe_count
    real_db_count, real_db_nodeids = _collect_pytest_tests(
        "tests",
        mark_expression="real_db",
    )
    counts["backend_pytest_real_db_count"] = real_db_count
    counts["backend_pytest_real_db_membership_digest"] = _pytest_membership_digest(real_db_nodeids)
    stateful_count, stateful_nodeids = _collect_pytest_tests(
        "tests",
        mark_expression="stateful_serial",
    )
    counts["backend_pytest_stateful_count"] = stateful_count
    counts["backend_pytest_stateful_membership_digest"] = _pytest_membership_digest(stateful_nodeids)
    cluster_count, cluster_nodeids = _collect_pytest_tests(
        "tests",
        mark_expression="cluster_serial",
    )
    counts["backend_pytest_cluster_count"] = cluster_count
    counts["backend_pytest_cluster_membership_digest"] = _pytest_membership_digest(cluster_nodeids)
    installer_count, installer_nodeids = _collect_pytest_tests("packaging/tests")
    counts["installer_pytest_count"] = installer_count
    _, packaging_parallel_nodeids = _collect_pytest_tests(
        "packaging/tests",
        mark_expression=PACKAGING_PARALLEL_MARKER,
    )
    _, packaging_serial_nodeids = _collect_pytest_tests(
        "packaging/tests",
        mark_expression=PACKAGING_SERIAL_MARKER,
    )

    print("Actuals:")
    for key, value in sorted(counts.items()):
        print(f"  {key:50} {value:6d}")
    print()

    current_memberships = {
        "backend_all": backend_nodeids,
        "backend_parallel": parallel_nodeids,
        "parallel_safe": parallel_safe_nodeids,
        "real_db": real_db_nodeids,
        "stateful_serial": stateful_nodeids,
        "cluster_serial": cluster_nodeids,
        "packaging_all": installer_nodeids,
        "packaging_parallel": packaging_parallel_nodeids,
        "packaging_serial": packaging_serial_nodeids,
    }
    base_readable, base_memberships, base_required, base_error = _collect_base_pytest_memberships(os.environ)
    metrics_exit = evaluate_pr_delta_metrics(counts)
    membership_exit = evaluate_protected_pytest_memberships(
        current_memberships,
        base_memberships,
        base_readable=base_readable,
        base_required=base_required,
        base_error=base_error,
    )
    return 1 if metrics_exit or membership_exit else 0


if __name__ == "__main__":
    sys.exit(main())

"""Exact-base admission gate for mutate-token ALLOWLIST changes.

The aggregate exemption count is not architecture debt: legitimate create,
append-only, terminal-state, and credential-lifecycle routes cannot carry a
prior row version.  A count-only ratchet is therefore the wrong control.

This lane protects the stronger contract instead.  Against the same exact Git
base used by the other release ratchets, it compares the complete
``route -> (reason, owner, touched tables, risk)`` mapping.  A non-empty delta
must exactly match the reviewed, clause-bound approval below.  Route
substitution, metadata drift, over/undershoot, and unreviewed future additions
all fail.  Once this change lands, base and current mappings match and the
approval auto-extinguishes without a flag.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _mutate_token_ledger import ALLOWLIST
from adr_contract_git import has_auditable_ci_context, select_ratchet_base

ContractEntry = tuple[str, str, tuple[str, ...], str]
AllowlistContract = dict[str, ContractEntry]
ApprovedEntry = tuple[ContractEntry, str]

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = "backend/scripts/_mutate_token_ledger.py"

# Every value contains the exact runtime exemption metadata and the authority
# reviewed for this one transition.  Existing-entry metadata changes are
# represented as one removal plus one addition and therefore cannot hide.
APPROVED_ADDITIONS: dict[str, ApprovedEntry] = {
    "POST /api/auth/desktop/activate": (
        ("session_rotation", "identity", ("auth_tokens", "devices"), "medium"),
        "ADR-0068-C01/C03/C08; API Desktop two-phase activation contract",
    ),
    "POST /api/ledgers/{ledger_id}/switch/prepare": (
        ("session_rotation", "identity", ("auth_tokens",), "medium"),
        "ADR-0068-C01/C03/C08; API Desktop two-phase ledger switch contract",
    ),
    "POST /web/debt-goals/create": (
        ("create_row", "goals", ("goals", "debt_goal_links"), "low"),
        "ADR-0049 section 6; ADR-0066-C08",
    ),
    "POST /web/debts": (
        ("create_row", "debts", ("debts",), "low"),
        "ADR-0049 section 5.1; ADR-0066-C01",
    ),
    "POST /web/debts/{public_id}/repayment-proposals": (
        ("create_row", "debts", ("member_repayment_proposals",), "low"),
        "ADR-0049 sections 3.2 and 5.2",
    ),
    "POST /web/debts/{public_id}/repayment-proposals/{proposal_public_id}/reject": (
        ("terminal_flag_flip", "debts", ("member_repayment_proposals",), "low"),
        "ADR-0049 sections 3.2 and 5.2",
    ),
    "POST /web/debts/{public_id}/repayment-proposals/{proposal_public_id}/withdraw": (
        ("terminal_flag_flip", "debts", ("member_repayment_proposals",), "low"),
        "ADR-0049 sections 3.2 and 5.2",
    ),
    "POST /web/expenses/new": (
        ("create_row", "expenses", ("expenses",), "low"),
        "ADR-0066-C01/C04/C08; API Web manual expense contract",
    ),
    "POST /web/repayment-drafts/{public_id}/dismiss": (
        ("terminal_flag_flip", "debts", ("repayment_drafts",), "low"),
        "ADR-0049 section 3.1; API Web repayment-draft contract",
    ),
}

APPROVED_REMOVALS: dict[str, ApprovedEntry] = {
    "POST /web/pending/batch-reject": (
        ("batch_db_write", "expenses", ("expenses",), "low"),
        "ADR-0038 confirmation; retired by the unified Web review contract",
    ),
    "POST /web/review/bulk": (
        ("batch_db_write", "expenses", ("expenses",), "low"),
        "ADR-0038 confirmation; retired by the unified Web review contract",
    ),
}


def _serialize_contract(raw_allowlist: object) -> AllowlistContract | None:
    if not isinstance(raw_allowlist, dict):
        return None
    contract: AllowlistContract = {}
    for route_key, entry in raw_allowlist.items():
        reason = getattr(entry, "reason_code", None)
        owner = getattr(entry, "owner", None)
        tables = getattr(entry, "touched_tables", None)
        risk = getattr(entry, "risk", None)
        if (
            not isinstance(route_key, str)
            or not isinstance(reason, str)
            or not isinstance(owner, str)
            or not isinstance(tables, tuple)
            or not all(isinstance(table, str) for table in tables)
            or not isinstance(risk, str)
        ):
            return None
        contract[route_key] = (reason, owner, tables, risk)
    return contract


def _load_base_contract(commit: str) -> tuple[AllowlistContract | None, str | None]:
    try:
        source = subprocess.check_output(
            ["git", "show", f"{commit}:{LEDGER_PATH}"],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None, f"cannot read {LEDGER_PATH} at exact base {commit}"
    # Reuse the already-imported module name so ``dataclass`` can resolve
    # ``sys.modules[cls.__module__]`` while evaluating the trusted base source.
    # The isolated namespace still prevents base assignments from mutating the
    # live module or its current ALLOWLIST.
    namespace: dict[str, object] = {"__name__": "_mutate_token_ledger"}
    try:
        exec(source, namespace)  # noqa: S102 - trusted repository source at exact base
    except Exception as exc:  # noqa: BLE001 - any base import drift is fail-closed
        return None, f"cannot evaluate base ALLOWLIST: {type(exc).__name__}"
    contract = _serialize_contract(namespace.get("ALLOWLIST"))
    if contract is None:
        return None, "base ALLOWLIST is missing or malformed"
    return contract, None


def _approval_metadata(approved: dict[str, ApprovedEntry]) -> AllowlistContract:
    return {route_key: entry for route_key, (entry, _authority) in approved.items()}


def _changed_contract(
    source: AllowlistContract,
    target: AllowlistContract,
) -> AllowlistContract:
    return {
        route_key: entry
        for route_key, entry in target.items()
        if route_key not in source or source[route_key] != entry
    }


def _mapping_failures(
    label: str,
    actual: AllowlistContract,
    expected: AllowlistContract,
) -> list[str]:
    failures: list[str] = []
    for route_key in sorted(set(expected) - set(actual)):
        failures.append(f"{label} missing approved route: {route_key}")
    for route_key in sorted(set(actual) - set(expected)):
        failures.append(f"{label} contains unapproved route: {route_key}")
    for route_key in sorted(set(actual) & set(expected)):
        if actual[route_key] != expected[route_key]:
            failures.append(
                f"{label} metadata mismatch for {route_key}: "
                f"actual={actual[route_key]!r}, approved={expected[route_key]!r}"
            )
    return failures


def _delta_failures(
    base: AllowlistContract,
    current: AllowlistContract,
    approved_additions: AllowlistContract,
    approved_removals: AllowlistContract,
) -> list[str]:
    if base == current:
        return []
    actual_additions = _changed_contract(base, current)
    actual_removals = _changed_contract(current, base)
    return [
        *_mapping_failures("addition", actual_additions, approved_additions),
        *_mapping_failures("removal", actual_removals, approved_removals),
    ]


def _approval_failures() -> list[str]:
    failures: list[str] = []
    for label, approved in (
        ("addition", APPROVED_ADDITIONS),
        ("removal", APPROVED_REMOVALS),
    ):
        for route_key, (_entry, authority) in approved.items():
            if not authority.startswith("ADR-"):
                failures.append(f"{label} {route_key} lacks an ADR authority")
    return failures


def _base_is_required() -> bool:
    if os.environ.get("XPJ_AUDIT_BASE_REF", "").strip():
        return True
    return has_auditable_ci_context(dict(os.environ))


def main() -> int:
    approval_failures = _approval_failures()
    current = _serialize_contract(ALLOWLIST)
    selected, selection_error = select_ratchet_base(REPO_ROOT, dict(os.environ))
    if current is None:
        print("FAIL: current mutate-token ALLOWLIST is malformed.")
        return 1
    if approval_failures:
        print("FAIL: mutate-token ALLOWLIST delta approval is malformed:")
        for failure in approval_failures:
            print(f"  - {failure}")
        return 1
    if selected is None:
        if _base_is_required():
            print(f"FAIL: exact mutate-token ALLOWLIST base is required: {selection_error}")
            return 1
        print("INFO: exact ALLOWLIST base unavailable in local exploration; CI will fail closed.")
        return 0

    base, load_error = _load_base_contract(selected.commit)
    if base is None:
        print(f"FAIL: {load_error}")
        return 1
    failures = _delta_failures(
        base,
        current,
        _approval_metadata(APPROVED_ADDITIONS),
        _approval_metadata(APPROVED_REMOVALS),
    )
    if failures:
        print("FAIL: mutate-token ALLOWLIST exact-base delta is not the reviewed contract:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    if base == current:
        print("PASS: mutate-token ALLOWLIST matches exact base; prior delta approval auto-extinguished.")
    else:
        print(
            "PASS: mutate-token ALLOWLIST exact-base delta matches "
            f"{len(APPROVED_ADDITIONS)} additions and {len(APPROVED_REMOVALS)} removals."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

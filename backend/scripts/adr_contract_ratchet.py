"""Base-relative ratchets for legacy ADRs and accepted decision history.

Current-tree parsing proves that one checkout is self-consistent.  These
ratchets compare that checkout with the merge base so a pull request cannot
re-sign legacy content or rewrite an already accepted schema-v2 decision.
Only two small generated JSON files are read on steady-state runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from adr_contract_git import (
    GitBase,
    bootstrap_legacy_files,
    commit_is_ancestor,
    git_json,
    git_text,
    select_ratchet_base,
)
from adr_contract_registry import (
    LEGACY_BASELINE_PATH,
    LEGACY_CALIBRATION_PATH,
    REPO_ROOT,
    Registry,
)

BASE_REGISTRY_PATH = "docs/current/adr-registry.json"
BASELINE_REPO_PATH = "docs/DECISIONS/legacy-baseline.json"
CALIBRATION_REPO_PATH = "docs/DECISIONS/legacy-calibration.json"
LOCKED_DECISION_TRANSITIONS = {
    "rejected": {"rejected"},
    "accepted": {"accepted", "deprecated", "superseded"},
    "deprecated": {"deprecated", "superseded"},
    "superseded": {"superseded"},
}


@dataclass(frozen=True)
class RatchetAudit:
    errors: tuple[str, ...]
    notices: tuple[str, ...] = ()


def legacy_ratchet_errors(
    base_baseline: dict[str, Any],
    current_baseline: dict[str, Any],
    base_calibration: dict[str, Any],
    current_calibration: dict[str, Any],
) -> list[str]:
    """Freeze history identity while allowing reviewed calibration changes."""

    errors: list[str] = []
    if base_baseline.get("bootstrap_base_commit") != current_baseline.get(
        "bootstrap_base_commit"
    ):
        errors.append("legacy baseline bootstrap_base_commit changed")

    base_rows, base_errors = _rows_by_id(base_baseline, "base legacy baseline")
    current_rows, current_errors = _rows_by_id(current_baseline, "current legacy baseline")
    base_current, base_current_errors = _rows_by_id(base_calibration, "base legacy calibration")
    current_current, current_current_errors = _rows_by_id(current_calibration, "current legacy calibration")
    errors.extend(
        (
            *base_errors,
            *current_errors,
            *base_current_errors,
            *current_current_errors,
        )
    )
    if base_errors or current_errors or base_current_errors or current_current_errors:
        return errors

    errors.extend(_identity_ratchet_errors(base_rows, current_rows))
    errors.extend(_calibration_root_errors(base_calibration, current_calibration))
    errors.extend(
        _calibration_ratchet_errors(
            base_current,
            current_current,
            current_rows,
        )
    )
    return errors


def _calibration_contract(row: dict[str, Any]) -> dict[str, Any]:
    review_fields = {"reviewed_at", "reviewed_against_commit", "reason"}
    return {key: value for key, value in row.items() if key not in review_fields}


def _identity_ratchet_errors(
    base_rows: dict[str, dict[str, Any]],
    current_rows: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    added = sorted(set(current_rows) - set(base_rows))
    if added:
        errors.append(f"legacy baseline added frozen rows: {', '.join(added)}")
    removed = sorted(set(base_rows) - set(current_rows))
    if removed:
        errors.append(
            "legacy baseline removed frozen rows; use a new successor ADR: "
            + ", ".join(removed)
        )
    for adr_id in sorted(set(base_rows) & set(current_rows)):
        if base_rows[adr_id] != current_rows[adr_id]:
            errors.append(f"ADR-{adr_id} retained legacy baseline row changed")
    return errors


def _calibration_ratchet_errors(
    base_rows: dict[str, dict[str, Any]],
    current_rows: dict[str, dict[str, Any]],
    current_identities: dict[str, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    added = sorted(set(current_rows) - set(base_rows))
    if added:
        errors.append("legacy calibration added rows outside the frozen baseline: " + ", ".join(added))
    retained = set(base_rows) & set(current_rows) & set(current_identities)
    for adr_id in sorted(retained):
        base = base_rows[adr_id]
        current = current_rows[adr_id]
        contract_changed = _calibration_contract(base) != _calibration_contract(current)
        if contract_changed:
            errors.extend(_calibration_change_errors(adr_id, base, current))
        errors.extend(_review_date_transition_errors(adr_id, base, current))
    missing = sorted(set(current_identities) - set(current_rows))
    if missing:
        errors.append("retained legacy ADRs lost calibration rows: " + ", ".join(missing))
    orphaned = sorted(set(current_rows) - set(current_identities))
    if orphaned:
        errors.append("legacy calibration rows lack retained baseline identity: " + ", ".join(orphaned))
    return errors


def _calibration_change_errors(
    adr_id: str, base: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    base_status = base.get("decision_status")
    current_status = current.get("decision_status")
    allowed = LOCKED_DECISION_TRANSITIONS.get(str(base_status))
    if allowed is not None and current_status not in allowed:
        errors.append(
            f"ADR-{adr_id} decision status cannot transition from "
            f"{base_status} to {current_status}"
        )
    if base.get("reason") == current.get("reason"):
        errors.append(f"ADR-{adr_id} calibration changed without an updated review reason")
    if base.get("reviewed_against_commit") == current.get("reviewed_against_commit"):
        errors.append(f"ADR-{adr_id} calibration changed without a new review commit")
    return errors


def _review_date_transition_errors(
    adr_id: str, base: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    try:
        base_date = date.fromisoformat(str(base.get("reviewed_at")))
        current_date = date.fromisoformat(str(current.get("reviewed_at")))
    except ValueError:
        return [f"ADR-{adr_id} calibration review date is malformed"]
    if current_date < base_date:
        return [f"ADR-{adr_id} calibration reviewed_at moved backwards"]
    return []


def _calibration_root_errors(
    base: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    try:
        base_date = date.fromisoformat(str(base.get("portfolio_reviewed_at")))
        current_date = date.fromisoformat(str(current.get("portfolio_reviewed_at")))
    except ValueError:
        return ["legacy calibration portfolio_reviewed_at is malformed"]
    if current_date < base_date:
        return ["legacy calibration portfolio_reviewed_at moved backwards"]
    return []


def bootstrap_legacy_errors(
    current_baseline: dict[str, Any],
    *,
    base_commit: str,
    committed_legacy_files: dict[str, tuple[str, str]],
) -> list[str]:
    """Bind the one-time baseline bootstrap exactly to the PR comparison base."""

    errors: list[str] = []
    if current_baseline.get("bootstrap_base_commit") != base_commit:
        errors.append("legacy baseline bootstrap_base_commit does not equal resolved PR base")
    current_rows, row_errors = _rows_by_id(current_baseline, "current")
    errors.extend(row_errors)
    if row_errors:
        return errors
    if set(current_rows) != set(committed_legacy_files):
        missing = sorted(set(committed_legacy_files) - set(current_rows))
        extra = sorted(set(current_rows) - set(committed_legacy_files))
        if missing:
            errors.append(f"legacy bootstrap omits base ADRs: {', '.join(missing)}")
        if extra:
            errors.append(f"legacy bootstrap adds non-base ADRs: {', '.join(extra)}")
    for adr_id in sorted(set(current_rows) & set(committed_legacy_files)):
        base_path, base_sha = committed_legacy_files[adr_id]
        row = current_rows[adr_id]
        if row.get("path") != base_path or row.get("sha256") != base_sha:
            errors.append(f"ADR-{adr_id} bootstrap row does not match base file identity")
    return errors


def accepted_history_ratchet_errors(base_registry: dict[str, Any], current_registry: Registry) -> list[str]:
    """Freeze the generated history fingerprint of every base-accepted v2 ADR."""

    raw_entries = base_registry.get("entries")
    if not isinstance(raw_entries, list):
        return ["base ADR registry entries must be an array"]
    current = {entry.adr_id: entry for entry in current_registry.entries}
    errors: list[str] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            errors.append("base ADR registry entry must be an object")
            continue
        base_status = raw.get("decision_status")
        if raw.get("source_kind") != "frontmatter":
            continue
        if not isinstance(base_status, str):
            errors.append("base schema-v2 ADR registry entry has invalid decision_status")
            continue
        if base_status not in LOCKED_DECISION_TRANSITIONS:
            continue
        adr_id = raw.get("id")
        if not isinstance(adr_id, str):
            errors.append("base accepted ADR registry entry has invalid id")
            continue
        base_fingerprint = raw.get("history_fingerprint")
        if not isinstance(base_fingerprint, str) or not base_fingerprint:
            errors.append(f"base accepted ADR-{adr_id} lacks history_fingerprint")
            continue
        entry = current.get(adr_id)
        if entry is None or entry.source_kind != "frontmatter":
            errors.append(f"accepted ADR-{adr_id} disappeared or reverted from schema v2")
            continue
        if entry.decision_status not in LOCKED_DECISION_TRANSITIONS[base_status]:
            errors.append(
                f"ADR-{adr_id} decision status cannot transition from {base_status} to {entry.decision_status}"
            )
        if entry.history_fingerprint != base_fingerprint:
            errors.append(
                f"ADR-{adr_id} frozen accepted history changed; "
                "write an amendment/superseding ADR"
            )
    return errors


def audit_base_ratchets(
    current_registry: Registry,
    *,
    repo_root: Path = REPO_ROOT,
    baseline_path: Path = LEGACY_BASELINE_PATH,
    calibration_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> RatchetAudit:
    """Load the selected Git base and run both base-relative ratchets."""

    environment = dict(environ or {})
    if environ is None:
        import os

        environment = dict(os.environ)
    base, base_error = select_ratchet_base(repo_root, environment)
    if base_error is not None:
        return RatchetAudit(errors=(base_error,))
    assert base is not None

    if calibration_path is None:
        calibration_path = baseline_path.with_name(LEGACY_CALIBRATION_PATH.name)
    current_baseline, load_error = _load_json_object(baseline_path, "current legacy baseline")
    if load_error is not None:
        return RatchetAudit(errors=(load_error,))
    current_calibration, load_error = _load_json_object(calibration_path, "current legacy calibration")
    if load_error is not None:
        return RatchetAudit(errors=(load_error,))
    assert current_baseline is not None
    assert current_calibration is not None

    binding_errors = _calibration_commit_errors(current_registry, repo_root)
    result = _audit_resolved_base(
        current_registry,
        repo_root=repo_root,
        base=base,
        current_baseline=current_baseline,
        current_calibration=current_calibration,
    )
    return RatchetAudit(errors=(*binding_errors, *result.errors), notices=result.notices)


def _audit_resolved_base(
    current_registry: Registry,
    *,
    repo_root: Path,
    base: GitBase,
    current_baseline: dict[str, Any],
    current_calibration: dict[str, Any],
) -> RatchetAudit:
    """Apply bootstrap or steady-state ratchets to an already resolved base."""

    errors: list[str] = []
    notices: list[str] = []
    try:
        base_baseline = git_json(repo_root, base.ref, BASELINE_REPO_PATH)
        base_calibration = git_json(repo_root, base.ref, CALIBRATION_REPO_PATH)
        base_registry = git_json(repo_root, base.ref, BASE_REGISTRY_PATH)
    except ValueError as exc:
        return RatchetAudit(errors=(str(exc),))
    if base_baseline is None:
        if base_calibration is not None:
            return RatchetAudit(errors=("ratchet base has calibration without a legacy baseline",))
        base_files, file_errors = bootstrap_legacy_files(repo_root, base.ref)
        errors.extend(file_errors)
        if not file_errors:
            errors.extend(
                bootstrap_legacy_errors(
                    current_baseline,
                    base_commit=base.commit,
                    committed_legacy_files=base_files,
                )
            )
            notices.append(
                "BOOTSTRAP: legacy rows are pinned exactly to the resolved PR base "
                f"{base.commit}"
            )
    else:
        if base_calibration is None:
            return RatchetAudit(errors=("ratchet base legacy baseline lacks legacy calibration",))
        errors.extend(
            legacy_ratchet_errors(
                base_baseline,
                current_baseline,
                base_calibration,
                current_calibration,
            )
        )

    if base_registry is not None:
        errors.extend(accepted_history_ratchet_errors(base_registry, current_registry))
    return RatchetAudit(errors=tuple(errors), notices=tuple(notices))


def _calibration_commit_errors(registry: Registry, repo_root: Path) -> list[str]:
    bindings = [
        ("legacy bootstrap base", registry.bootstrap_base_commit),
        ("portfolio code baseline", registry.code_baseline),
    ]
    bindings.extend(
        (f"ADR-{entry.adr_id} calibration review", entry.reviewed_against_commit)
        for entry in registry.entries
        if entry.source_kind == "legacy-baseline"
    )
    errors: list[str] = []
    for label, commit in bindings:
        if commit is None:
            errors.append(f"{label} commit is missing")
            continue
        resolved = git_text(repo_root, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
        if resolved != commit:
            errors.append(f"{label} commit {commit!r} cannot be resolved exactly")
        elif not commit_is_ancestor(repo_root, commit):
            errors.append(f"{label} commit {commit!r} is not an ancestor of HEAD")
    return errors


def _load_json_object(path: Path, label: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot load {label}: {exc}"
    if not isinstance(value, dict):
        return None, f"{label} root must be an object"
    return value, None


def _rows_by_id(source: dict[str, Any], label: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    rows = source.get("entries")
    if not isinstance(rows, list):
        return {}, [f"{label} entries must be an array"]
    result: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            errors.append(f"{label} contains malformed row")
            continue
        adr_id = row["id"]
        if adr_id in result:
            errors.append(f"{label} repeats ADR-{adr_id}")
            continue
        result[adr_id] = row
    return result, errors

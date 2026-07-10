"""Build the authoritative ADR registry from v2 front matter and legacy sources.

Schema-v2 front matter is authoritative for new ADRs.  Existing legacy ADRs
remain permanently frozen: ``legacy-baseline.json`` records historical identity
(ID/path/SHA-256), while ``legacy-calibration.json`` carries reviewable current
metadata.  Keeping those concerns separate lets a code-backed review correct a
legacy ADR's current status without creating a history re-signing channel.
JSON and Markdown projections live in :mod:`adr_contract_views`.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from adr_contract_registry_types import Registry, RegistryEntry, RegistryError
from adr_contract_schema import (
    CONFIDENCE_LEVELS,
    DECISION_STATUSES,
    DECISION_TYPES,
    IMPLEMENTATION_STATUSES,
    RELATION_KINDS,
    RISK_LEVELS,
    VERIFICATION_STATUSES,
    AdrRelation,
    AdrSchemaError,
    has_v2_front_matter,
    parse_adr,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS_DIR = REPO_ROOT / "docs" / "DECISIONS"
LEGACY_BASELINE_PATH = DECISIONS_DIR / "legacy-baseline.json"
LEGACY_CALIBRATION_PATH = DECISIONS_DIR / "legacy-calibration.json"
REGISTRY_SCHEMA_VERSION = 2
LEGACY_BASELINE_SCHEMA_VERSION = 3
LEGACY_CALIBRATION_SCHEMA_VERSION = 2
ADR_FILE_RE = re.compile(r"^(?P<id>\d{4})-(?:[a-z0-9]+(?:[.-][a-z0-9]+)*)\.md$")
NON_ADR_MARKDOWN = {"README.md"}
RESERVED_ADR_IDS = {"0032", "0033", "0034"}
LEGACY_MAX_ADR_ID = 61
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ACYCLIC_RELATIONS = {
    "depends-on",
    "refines",
    "amends",
    "supersedes",
    "implements",
    "deprecates",
}

def build_registry(
    *,
    decisions_dir: Path = DECISIONS_DIR,
    legacy_baseline_path: Path = LEGACY_BASELINE_PATH,
    legacy_calibration_path: Path | None = None,
) -> Registry:
    """Build and validate the registry from source files."""

    if legacy_calibration_path is None:
        legacy_calibration_path = legacy_baseline_path.with_name(LEGACY_CALIBRATION_PATH.name)
    baseline = _load_legacy_baseline(legacy_baseline_path)
    calibration = _load_legacy_calibration(legacy_calibration_path)
    files = _decision_files(decisions_dir)
    identity_rows = _legacy_identity_rows_by_id(baseline)
    calibration_rows = _legacy_calibration_rows_by_id(calibration)
    _validate_legacy_source_alignment(identity_rows, calibration_rows)
    entries: list[RegistryEntry] = []
    for adr_id, path in sorted(files.items()):
        text = path.read_text(encoding="utf-8")
        if has_v2_front_matter(text):
            entries.append(_entry_from_v2(path, decisions_dir))
            if adr_id in identity_rows or adr_id in calibration_rows:
                raise RegistryError(f"ADR-{adr_id} uses schema v2 but remains in frozen legacy sources")
            continue
        identity = identity_rows.get(adr_id)
        current = calibration_rows.get(adr_id)
        if identity is None or current is None:
            raise RegistryError(f"ADR-{adr_id} has no v2 front matter and is absent from legacy sources")
        entries.append(_entry_from_legacy(path, decisions_dir, identity, current))

    orphaned = sorted(set(identity_rows) - set(files))
    if orphaned:
        raise RegistryError(f"legacy baseline references missing ADRs: {', '.join(orphaned)}")
    registry = Registry(
        schema_version=REGISTRY_SCHEMA_VERSION,
        front_matter_schema_version=_required_int(calibration, "front_matter_schema_version"),
        portfolio_reviewed_at=_required_string(calibration, "portfolio_reviewed_at"),
        code_baseline=_required_string(calibration, "code_baseline"),
        bootstrap_base_commit=_required_string(baseline, "bootstrap_base_commit"),
        baseline_scope=_required_string(calibration, "baseline_scope"),
        entries=tuple(entries),
    )
    if registry.front_matter_schema_version != 2:
        raise RegistryError("legacy calibration front_matter_schema_version must be 2")
    _validate_portfolio_metadata(registry)
    _validate_registry(registry)
    return registry


def _load_legacy_baseline(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read legacy ADR baseline: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistryError("legacy ADR baseline root must be an object")
    expected_fields = {
        "schema_version",
        "bootstrap_base_commit",
        "entries",
    }
    if set(value) != expected_fields:
        raise RegistryError("legacy ADR baseline root has missing or unknown fields")
    if _required_int(value, "schema_version") != LEGACY_BASELINE_SCHEMA_VERSION:
        raise RegistryError(
            f"legacy baseline schema_version must be {LEGACY_BASELINE_SCHEMA_VERSION}"
        )
    return value


def _load_legacy_calibration(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read legacy ADR calibration: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistryError("legacy ADR calibration root must be an object")
    expected_fields = {
        "schema_version",
        "front_matter_schema_version",
        "portfolio_reviewed_at",
        "code_baseline",
        "baseline_scope",
        "entries",
    }
    if set(value) != expected_fields:
        raise RegistryError("legacy ADR calibration root has missing or unknown fields")
    if _required_int(value, "schema_version") != LEGACY_CALIBRATION_SCHEMA_VERSION:
        raise RegistryError(
            f"legacy ADR calibration schema_version must be {LEGACY_CALIBRATION_SCHEMA_VERSION}"
        )
    return value


def _decision_files(decisions_dir: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(decisions_dir.glob("*.md")):
        if path.name in NON_ADR_MARKDOWN:
            continue
        match = ADR_FILE_RE.fullmatch(path.name)
        if match is None:
            raise RegistryError(f"invalid ADR filename {path.name!r}")
        adr_id = match.group("id")
        if adr_id in RESERVED_ADR_IDS:
            raise RegistryError(f"ADR id {adr_id} is reserved")
        if adr_id in result:
            raise RegistryError(f"duplicate ADR id {adr_id}")
        result[adr_id] = path
    return result


def _legacy_identity_rows_by_id(
    baseline: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    rows = baseline.get("entries")
    if not isinstance(rows, list):
        raise RegistryError("legacy baseline entries must be an array")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RegistryError("legacy baseline entry must be an object")
        if set(row) != {"id", "path", "sha256"}:
            raise RegistryError("legacy baseline entry has missing or unknown fields")
        adr_id = _required_string(row, "id")
        if not re.fullmatch(r"\d{4}", adr_id):
            raise RegistryError(f"invalid legacy baseline ADR id {adr_id!r}")
        if int(adr_id) > LEGACY_MAX_ADR_ID:
            raise RegistryError(f"ADR-{adr_id} cannot be added to the closed legacy baseline")
        if adr_id in RESERVED_ADR_IDS:
            raise RegistryError(f"ADR id {adr_id} is reserved")
        if adr_id in result:
            raise RegistryError(f"duplicate legacy baseline ADR-{adr_id}")
        result[adr_id] = row
    return result


def _legacy_calibration_rows_by_id(
    calibration: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    rows = calibration.get("entries")
    if not isinstance(rows, list):
        raise RegistryError("legacy calibration entries must be an array")
    result: dict[str, dict[str, Any]] = {}
    expected_fields = {
        "id",
        "path",
        "title",
        "summary",
        "current_scope",
        "decision_status",
        "implementation_status",
        "verification_status",
        "decision_type",
        "risk_level",
        "confidence",
        "owners",
        "relations",
        "reviewed_at",
        "reviewed_against_commit",
        "reason",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise RegistryError("legacy calibration entry has missing or unknown fields")
        adr_id = _required_string(row, "id")
        if not re.fullmatch(r"\d{4}", adr_id):
            raise RegistryError(f"invalid legacy calibration ADR id {adr_id!r}")
        if int(adr_id) > LEGACY_MAX_ADR_ID:
            raise RegistryError(f"ADR-{adr_id} cannot be added to the closed legacy calibration")
        if adr_id in RESERVED_ADR_IDS:
            raise RegistryError(f"ADR id {adr_id} is reserved")
        if adr_id in result:
            raise RegistryError(f"duplicate legacy calibration ADR-{adr_id}")
        _validate_calibration_review(row, adr_id)
        result[adr_id] = row
    return result


def _validate_legacy_source_alignment(
    identity_rows: dict[str, dict[str, Any]],
    calibration_rows: dict[str, dict[str, Any]],
) -> None:
    missing = sorted(set(identity_rows) - set(calibration_rows))
    if missing:
        raise RegistryError(f"legacy baseline rows lack calibration: {', '.join(missing)}")
    extra = sorted(set(calibration_rows) - set(identity_rows))
    if extra:
        raise RegistryError(f"legacy calibration references absent or migrated ADRs: {', '.join(extra)}")
    for adr_id in sorted(identity_rows):
        if identity_rows[adr_id]["path"] != calibration_rows[adr_id]["path"]:
            raise RegistryError(f"ADR-{adr_id} legacy source paths do not match")


def _validate_calibration_review(row: dict[str, Any], adr_id: str) -> None:
    reviewed_at = _canonical_review_date(
        _required_string(row, "reviewed_at"),
        f"ADR-{adr_id} calibration reviewed_at",
    )
    if reviewed_at > date.today():
        raise RegistryError(f"ADR-{adr_id} calibration reviewed_at must not be in the future")
    commit = _required_string(row, "reviewed_against_commit")
    if GIT_COMMIT_RE.fullmatch(commit) is None:
        raise RegistryError(f"ADR-{adr_id} calibration reviewed_against_commit must be a 40-character commit")
    _legacy_table_string(row, "reason")


def _entry_from_v2(path: Path, decisions_dir: Path) -> RegistryEntry:
    try:
        parsed = parse_adr(path)
    except AdrSchemaError as exc:
        raise RegistryError(str(exc)) from exc
    metadata = parsed.metadata
    return RegistryEntry(
        adr_id=metadata.adr_id,
        path=path.relative_to(decisions_dir.parent.parent).as_posix(),
        title=metadata.title,
        summary=metadata.summary,
        current_scope=metadata.current_scope,
        schema_version=metadata.schema_version,
        source_kind="frontmatter",
        decision_status=metadata.decision_status,
        implementation_status=metadata.implementation_status,
        verification_status=metadata.verification_status,
        decision_type=metadata.decision_type,
        risk_level=metadata.risk_level,
        confidence=metadata.confidence,
        decision_owner=metadata.decision_owner,
        implementation_owner=metadata.implementation_owner,
        verification_owner=metadata.verification_owner,
        risk_owner=metadata.risk_owner,
        relations=metadata.relations,
        clause_ids=parsed.clause_ids,
        reviewed_at=None,
        reviewed_against_commit=None,
        calibration_reason=None,
        history_fingerprint=parsed.history_fingerprint,
    )


def _entry_from_legacy(
    path: Path,
    decisions_dir: Path,
    identity: dict[str, Any],
    calibration: dict[str, Any],
) -> RegistryEntry:
    adr_id = _required_string(identity, "id")
    if not path.name.startswith(f"{adr_id}-"):
        raise RegistryError(f"{path.name}: legacy baseline id does not match filename")
    expected_path = path.relative_to(decisions_dir.parent.parent).as_posix()
    if _required_string(identity, "path") != expected_path:
        raise RegistryError(f"ADR-{adr_id} legacy baseline path does not match file")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    expected_hash = _required_string(identity, "sha256")
    if SHA256_RE.fullmatch(expected_hash) is None:
        raise RegistryError(f"ADR-{adr_id} legacy baseline sha256 is malformed")
    if actual_hash != expected_hash:
        raise RegistryError(
            f"ADR-{adr_id} changed outside the legacy ratchet; "
            "restore the frozen body and express the new direction in a successor ADR"
        )
    if _required_string(calibration, "id") != adr_id:
        raise RegistryError(f"ADR-{adr_id} legacy calibration id does not match baseline")
    if _required_string(calibration, "path") != expected_path:
        raise RegistryError(f"ADR-{adr_id} legacy calibration path does not match file")
    raw_relations = calibration["relations"]
    if not isinstance(raw_relations, list):
        raise RegistryError(f"{path.name}: legacy relations must be an array")
    relations = tuple(_legacy_relation(path, item) for item in raw_relations)
    if len({(item.kind, item.target) for item in relations}) != len(relations):
        raise RegistryError(f"{path.name}: duplicate legacy relation")
    owners = calibration.get("owners")
    if not isinstance(owners, dict) or set(owners) != {
        "decision",
        "implementation",
        "verification",
        "risk",
    }:
        raise RegistryError(f"{path.name}: legacy owners must contain four roles")
    decision_status = _legacy_enum(calibration, "decision_status", DECISION_STATUSES)
    implementation_status = _legacy_enum(calibration, "implementation_status", IMPLEMENTATION_STATUSES)
    verification_status = _legacy_enum(calibration, "verification_status", VERIFICATION_STATUSES)
    if verification_status == "verified":
        raise RegistryError(f"ADR-{adr_id} is legacy and cannot be verified without stable clauses")
    return RegistryEntry(
        adr_id=adr_id,
        path=path.relative_to(decisions_dir.parent.parent).as_posix(),
        title=_legacy_table_string(calibration, "title"),
        summary=_legacy_table_string(calibration, "summary"),
        current_scope=_legacy_table_string(calibration, "current_scope"),
        schema_version=1,
        source_kind="legacy-baseline",
        decision_status=decision_status,
        implementation_status=implementation_status,
        verification_status=verification_status,
        decision_type=_legacy_enum(calibration, "decision_type", DECISION_TYPES),
        risk_level=_legacy_enum(calibration, "risk_level", RISK_LEVELS),
        confidence=_legacy_enum(calibration, "confidence", CONFIDENCE_LEVELS),
        decision_owner=_required_string(owners, "decision"),
        implementation_owner=_required_string(owners, "implementation"),
        verification_owner=_required_string(owners, "verification"),
        risk_owner=_required_string(owners, "risk"),
        relations=relations,
        clause_ids=(),
        reviewed_at=_required_string(calibration, "reviewed_at"),
        reviewed_against_commit=_required_string(calibration, "reviewed_against_commit"),
        calibration_reason=_required_string(calibration, "reason"),
        history_fingerprint=None,
    )


def _legacy_relation(path: Path, raw: Any) -> AdrRelation:
    if not isinstance(raw, dict) or set(raw) != {"kind", "target", "scope"}:
        raise RegistryError(f"{path.name}: malformed legacy relation")
    kind = raw["kind"]
    if not isinstance(kind, str) or kind not in RELATION_KINDS:
        raise RegistryError(f"{path.name}: invalid legacy relation kind {kind!r}")
    return AdrRelation(
        kind=kind,
        target=_required_string(raw, "target"),
        scope=_legacy_table_string(raw, "scope"),
    )


def _validate_registry(registry: Registry) -> None:
    by_id = {entry.adr_id: entry for entry in registry.entries}
    if len(by_id) != len(registry.entries):
        raise RegistryError("registry contains duplicate ADR ids")
    for entry in registry.entries:
        for relation in entry.relations:
            if relation.target not in by_id:
                raise RegistryError(f"ADR-{entry.adr_id} {relation.kind} missing ADR-{relation.target}")
            if relation.target == entry.adr_id:
                raise RegistryError(f"ADR-{entry.adr_id} has a self relation")
            target = by_id[relation.target]
            if (
                relation.kind == "conflicts-with"
                and entry.decision_status == "accepted"
                and target.decision_status == "accepted"
            ):
                raise RegistryError(f"accepted ADR-{entry.adr_id} conflicts with accepted ADR-{target.adr_id}")
            if (
                entry.decision_status == "accepted"
                and relation.kind == "depends-on"
                and target.decision_status in {"rejected", "superseded"}
            ):
                raise RegistryError(f"accepted ADR-{entry.adr_id} depends on inactive ADR-{target.adr_id}")
            if (
                entry.decision_status == "accepted"
                and relation.kind == "supersedes"
                and target.decision_status != "superseded"
            ):
                raise RegistryError(
                    f"ADR-{entry.adr_id} supersedes ADR-{target.adr_id}, but target is {target.decision_status}"
                )
    _validate_acyclic_relations(registry.entries)


def _validate_portfolio_metadata(registry: Registry) -> None:
    reviewed_at = _canonical_review_date(
        registry.portfolio_reviewed_at,
        "legacy calibration portfolio_reviewed_at",
    )
    if reviewed_at > date.today():
        raise RegistryError("legacy calibration portfolio_reviewed_at must not be in the future")
    if GIT_COMMIT_RE.fullmatch(registry.code_baseline) is None:
        raise RegistryError("legacy calibration code_baseline must be a 40-character commit")
    if GIT_COMMIT_RE.fullmatch(registry.bootstrap_base_commit) is None:
        raise RegistryError("legacy baseline bootstrap_base_commit must be a 40-character commit")


def _canonical_review_date(value: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RegistryError(f"{label} must be a canonical ISO date") from exc
    if parsed.isoformat() != value:
        raise RegistryError(f"{label} must be a canonical ISO date")
    return parsed


def _validate_acyclic_relations(entries: tuple[RegistryEntry, ...]) -> None:
    graph = {
        entry.adr_id: {relation.target for relation in entry.relations if relation.kind in ACYCLIC_RELATIONS}
        for entry in entries
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, path: tuple[str, ...]) -> None:
        if node in visiting:
            raise RegistryError(f"ADR relation cycle: {' -> '.join((*path, node))}")
        if node in visited:
            return
        visiting.add(node)
        for target in sorted(graph.get(node, set())):
            visit(target, (*path, node))
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, ())


def _required_string(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"legacy baseline field {field!r} must be a non-empty string")
    return value.strip()


def _required_int(raw: dict[str, Any], field: str) -> int:
    value = raw.get(field)
    if type(value) is not int:
        raise RegistryError(f"legacy baseline field {field!r} must be an integer")
    return value


def _legacy_table_string(raw: dict[str, Any], field: str) -> str:
    value = _required_string(raw, field)
    if "|" in value or "\n" in value or "\r" in value:
        raise RegistryError(f"legacy baseline field {field!r} must not contain table delimiters or newlines")
    return value


def _legacy_enum(raw: dict[str, Any], field: str, allowed: set[str]) -> str:
    value = _required_string(raw, field)
    if value not in allowed:
        raise RegistryError(f"legacy baseline field {field!r} must be one of {', '.join(sorted(allowed))}")
    return value

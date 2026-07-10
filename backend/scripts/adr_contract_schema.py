"""Schema-v2 ADR front matter and stable-clause validation.

The contract format deliberately uses TOML front matter so the repository can
parse it with Python's standard library.  This module validates one ADR only;
portfolio relations and legacy ratchets live in :mod:`adr_contract_registry`.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from adr_contract_history import history_fingerprint

FRONT_MATTER_DELIMITER = "+++"
FRONT_MATTER_SCHEMA_VERSION = 2

DECISION_STATUSES = {"proposed", "accepted", "rejected", "deprecated", "superseded"}
IMPLEMENTATION_STATUSES = {
    "not-started",
    "implementing",
    "partial",
    "implemented",
    "nonconformant",
}
VERIFICATION_STATUSES = {"unverified", "verified", "failed", "stale"}
DECISION_TYPES = {
    "domain", "data-consistency", "security-identity",
    "deployment-runtime", "client-interaction", "performance-capacity",
    "dependency-technology", "migration-retirement", "governance-calibration",
}
RISK_LEVELS = {"low", "standard", "high", "critical"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
RELATION_KINDS = {
    "depends-on", "refines", "amends", "supersedes",
    "conflicts-with", "implements", "deprecates", "informational",
}

MANDATORY_CLAUSE_SUFFIXES = (
    "SCOPE", "ASSUMPTIONS", "DRIVERS", "ALTERNATIVES", "DECISION",
    "CONSEQUENCES", "REVERSIBILITY", "EVIDENCE", "REFERENCES",
)
CLAUSE_ID_RE = re.compile(r"^ADR-(?P<id>\d{4})-(?P<suffix>[A-Z][A-Z0-9-]*)$")
HEADING_CLAUSE_RE = re.compile(
    r"^#{2,3}\s+\[(?P<clause>ADR-\d{4}-[A-Z][A-Z0-9-]*)\]\s+\S.*$"
)
H2_RE = re.compile(r"^##(?:[ \t]+.*)?$")
FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")
H1_RE = re.compile(r"^#\s+(?P<id>\d{4})\s+\S.*$")
ADR_ID_RE = re.compile(r"^\d{4}$")


@dataclass(frozen=True)
class AdrRelation:
    kind: str
    target: str
    scope: str


@dataclass(frozen=True)
class AdrMetadata:
    schema_version: int
    adr_id: str
    title: str
    summary: str
    current_scope: str
    date: str
    decision_status: str
    implementation_status: str
    verification_status: str
    decision_type: str
    risk_level: str
    confidence: str
    decision_owner: str
    implementation_owner: str
    verification_owner: str
    risk_owner: str
    relations: tuple[AdrRelation, ...]


@dataclass(frozen=True)
class ParsedAdr:
    metadata: AdrMetadata
    body: str
    clause_ids: tuple[str, ...]
    history_fingerprint: str


@dataclass
class _BodyScan:
    clause_ids: list[str]
    h2_clause_ids: list[str]
    cxx_parents: dict[str, str | None]
    sections: dict[str, list[str]]
    untracked_h2: list[str]


class AdrSchemaError(ValueError):
    """Raised when one schema-v2 ADR is malformed."""


def has_v2_front_matter(text: str) -> bool:
    """Return whether ``text`` starts with the schema-v2 delimiter."""

    return text.startswith(f"{FRONT_MATTER_DELIMITER}\n")


def parse_adr(path: Path) -> ParsedAdr:
    """Parse and validate one schema-v2 ADR."""

    text = path.read_text(encoding="utf-8")
    raw_metadata, body = _split_front_matter(path, text)
    metadata = _metadata_from_dict(path, raw_metadata)
    clause_ids = _validate_body(path, metadata, body)
    return ParsedAdr(
        metadata=metadata,
        body=body,
        clause_ids=clause_ids,
        history_fingerprint=history_fingerprint(
            adr_id=metadata.adr_id,
            title=metadata.title,
            decision_date=metadata.date,
            summary=metadata.summary,
            current_scope=metadata.current_scope,
            relations=tuple(
                (relation.kind, relation.target, relation.scope)
                for relation in metadata.relations
            ),
            body=body,
        ),
    )


def _split_front_matter(path: Path, text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0] != FRONT_MATTER_DELIMITER:
        raise AdrSchemaError(f"{path.name}: missing TOML front matter")
    try:
        closing = lines.index(FRONT_MATTER_DELIMITER, 1)
    except ValueError as exc:
        raise AdrSchemaError(f"{path.name}: unclosed TOML front matter") from exc
    source = "\n".join(lines[1:closing])
    try:
        parsed = tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        raise AdrSchemaError(f"{path.name}: invalid TOML front matter: {exc}") from exc
    body = "\n".join(lines[closing + 1 :]).lstrip("\n")
    if text.endswith("\n"):
        body += "\n"
    return parsed, body


def _metadata_from_dict(path: Path, raw: dict[str, Any]) -> AdrMetadata:
    required = {
        "schema_version",
        "id",
        "title",
        "summary",
        "current_scope",
        "date",
        "decision_status",
        "implementation_status",
        "verification_status",
        "decision_type",
        "risk_level",
        "confidence",
        "decision_owner",
        "implementation_owner",
        "verification_owner",
        "risk_owner",
    }
    missing = sorted(required - raw.keys())
    unknown = sorted(raw.keys() - required - {"relations"})
    if missing:
        raise AdrSchemaError(f"{path.name}: missing front matter fields: {', '.join(missing)}")
    if unknown:
        raise AdrSchemaError(f"{path.name}: unknown front matter fields: {', '.join(unknown)}")

    schema_version = raw["schema_version"]
    if type(schema_version) is not int or schema_version != FRONT_MATTER_SCHEMA_VERSION:
        raise AdrSchemaError(
            f"{path.name}: schema_version must be {FRONT_MATTER_SCHEMA_VERSION} as an integer"
        )
    adr_id = _required_string(path, raw, "id")
    if not ADR_ID_RE.fullmatch(adr_id) or not path.name.startswith(f"{adr_id}-"):
        raise AdrSchemaError(f"{path.name}: front matter id does not match filename")
    date_value = _required_string(path, raw, "date")
    try:
        if date.fromisoformat(date_value).isoformat() != date_value:
            raise ValueError
    except ValueError as exc:
        raise AdrSchemaError(f"{path.name}: date must be canonical ISO YYYY-MM-DD") from exc

    relations = _relations_from_list(path, adr_id, raw.get("relations", []))
    metadata = AdrMetadata(
        schema_version=schema_version,
        adr_id=adr_id,
        title=_table_safe_string(path, raw, "title"),
        summary=_table_safe_string(path, raw, "summary"),
        current_scope=_table_safe_string(path, raw, "current_scope"),
        date=date_value,
        decision_status=_enum_value(path, raw, "decision_status", DECISION_STATUSES),
        implementation_status=_enum_value(
            path, raw, "implementation_status", IMPLEMENTATION_STATUSES
        ),
        verification_status=_enum_value(
            path, raw, "verification_status", VERIFICATION_STATUSES
        ),
        decision_type=_enum_value(path, raw, "decision_type", DECISION_TYPES),
        risk_level=_enum_value(path, raw, "risk_level", RISK_LEVELS),
        confidence=_enum_value(path, raw, "confidence", CONFIDENCE_LEVELS),
        decision_owner=_required_string(path, raw, "decision_owner"),
        implementation_owner=_required_string(path, raw, "implementation_owner"),
        verification_owner=_required_string(path, raw, "verification_owner"),
        risk_owner=_required_string(path, raw, "risk_owner"),
        relations=relations,
    )
    _validate_state_combination(path, metadata)
    return metadata


def _required_string(path: Path, raw: dict[str, Any], field: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value.strip():
        raise AdrSchemaError(f"{path.name}: {field} must be a non-empty string")
    return value.strip()


def _table_safe_string(path: Path, raw: dict[str, Any], field: str) -> str:
    value = _required_string(path, raw, field)
    if "|" in value or "\n" in value or "\r" in value:
        raise AdrSchemaError(
            f"{path.name}: {field} must not contain table delimiters or newlines"
        )
    return value


def _enum_value(path: Path, raw: dict[str, Any], field: str, allowed: set[str]) -> str:
    value = _required_string(path, raw, field)
    if value not in allowed:
        raise AdrSchemaError(
            f"{path.name}: {field} must be one of {', '.join(sorted(allowed))}"
        )
    return value


def _relations_from_list(
    path: Path, adr_id: str, raw_relations: Any
) -> tuple[AdrRelation, ...]:
    if not isinstance(raw_relations, list):
        raise AdrSchemaError(f"{path.name}: relations must be an array of TOML tables")
    relations: list[AdrRelation] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_relations):
        if not isinstance(item, dict) or set(item) != {"kind", "target", "scope"}:
            raise AdrSchemaError(
                f"{path.name}: relations[{index}] requires kind, target, and scope"
            )
        kind = item["kind"]
        target = item["target"]
        scope = item["scope"]
        if not isinstance(kind, str) or kind not in RELATION_KINDS:
            raise AdrSchemaError(f"{path.name}: invalid relation kind {kind!r}")
        if not isinstance(target, str) or not ADR_ID_RE.fullmatch(target):
            raise AdrSchemaError(f"{path.name}: invalid relation target {target!r}")
        if target == adr_id:
            raise AdrSchemaError(f"{path.name}: ADR cannot relate to itself")
        if not isinstance(scope, str) or not scope.strip():
            raise AdrSchemaError(f"{path.name}: relation scope must be explicit")
        if "|" in scope or "\n" in scope or "\r" in scope:
            raise AdrSchemaError(
                f"{path.name}: relation scope must not contain table delimiters or newlines"
            )
        key = (kind, target)
        if key in seen:
            raise AdrSchemaError(f"{path.name}: duplicate relation {kind} -> {target}")
        seen.add(key)
        relations.append(AdrRelation(kind=kind, target=target, scope=scope.strip()))
    return tuple(relations)


def _validate_state_combination(path: Path, metadata: AdrMetadata) -> None:
    if (
        metadata.decision_status in {"rejected", "superseded"}
        and metadata.verification_status == "verified"
    ):
        raise AdrSchemaError(
            f"{path.name}: rejected/superseded decision cannot be currently verified"
        )
    if (
        metadata.implementation_status == "nonconformant"
        and metadata.verification_status == "verified"
    ):
        raise AdrSchemaError(
            f"{path.name}: nonconformant implementation cannot be verified"
        )


def _validate_body(
    path: Path, metadata: AdrMetadata, body: str
) -> tuple[str, ...]:
    lines = _visible_markdown(body).splitlines()
    _validate_h1(path, metadata.adr_id, lines)
    scan = _scan_body(lines, metadata.adr_id)
    _validate_clause_structure(path, metadata.adr_id, scan)
    _validate_section_substance(path, metadata.adr_id, scan.sections)
    return tuple(scan.clause_ids)


def _validate_h1(path: Path, adr_id: str, lines: list[str]) -> None:
    h1_lines = [line for line in lines if line.startswith("# ")]
    if len(h1_lines) != 1:
        raise AdrSchemaError(f"{path.name}: body must contain exactly one H1")
    match = H1_RE.fullmatch(h1_lines[0])
    if match is None or match.group("id") != adr_id:
        raise AdrSchemaError(f"{path.name}: H1 id must match front matter id")


def _scan_body(lines: list[str], adr_id: str) -> _BodyScan:
    scan = _BodyScan([], [], {}, {}, [])
    current_h2: str | None = None
    for line in lines:
        if H2_RE.fullmatch(line):
            current_h2 = None
        heading_match = HEADING_CLAUSE_RE.fullmatch(line)
        if heading_match is None:
            if H2_RE.fullmatch(line):
                scan.untracked_h2.append(line)
            if current_h2 is not None:
                scan.sections[current_h2].append(line)
            continue
        clause = heading_match.group("clause")
        scan.clause_ids.append(clause)
        if line.startswith("## "):
            scan.h2_clause_ids.append(clause)
            current_h2 = clause
            scan.sections.setdefault(clause, [])
        else:
            if re.fullmatch(rf"ADR-{adr_id}-C\d{{2}}", clause):
                scan.cxx_parents[clause] = current_h2
            if current_h2 is not None:
                scan.sections[current_h2].append(line)
    return scan


def _validate_clause_structure(path: Path, adr_id: str, scan: _BodyScan) -> None:
    duplicates = sorted(
        {item for item in scan.clause_ids if scan.clause_ids.count(item) > 1}
    )
    if duplicates:
        raise AdrSchemaError(
            f"{path.name}: duplicate clause ids: {', '.join(duplicates)}"
        )
    if scan.untracked_h2:
        raise AdrSchemaError(
            f"{path.name}: every H2 requires a stable clause id: "
            f"{', '.join(scan.untracked_h2)}"
        )
    wrong_owner = [
        clause
        for clause in scan.clause_ids
        if (match := CLAUSE_ID_RE.fullmatch(clause)) is None
        or match.group("id") != adr_id
    ]
    if wrong_owner:
        raise AdrSchemaError(
            f"{path.name}: foreign/malformed clause ids: {', '.join(wrong_owner)}"
        )
    required = {f"ADR-{adr_id}-{suffix}" for suffix in MANDATORY_CLAUSE_SUFFIXES}
    missing = sorted(required - set(scan.h2_clause_ids))
    if missing:
        raise AdrSchemaError(
            f"{path.name}: missing mandatory clause ids: {', '.join(missing)}"
        )
    if not scan.cxx_parents:
        raise AdrSchemaError(f"{path.name}: Decision requires at least one stable Cxx clause")
    decision_clause = f"ADR-{adr_id}-DECISION"
    misplaced = sorted(
        clause
        for clause, parent in scan.cxx_parents.items()
        if parent != decision_clause
    )
    if misplaced:
        raise AdrSchemaError(
            f"{path.name}: Cxx clauses must belong to {decision_clause}: "
            f"{', '.join(misplaced)}"
        )


def _validate_section_substance(
    path: Path, adr_id: str, sections: dict[str, list[str]]
) -> None:
    for suffix in MANDATORY_CLAUSE_SUFFIXES:
        clause = f"ADR-{adr_id}-{suffix}"
        if not "\n".join(sections.get(clause, [])).strip():
            raise AdrSchemaError(f"{path.name}: clause {clause} must not be empty")
    alternatives = sections[f"ADR-{adr_id}-ALTERNATIVES"]
    option_count = sum(line.lstrip().startswith("- ") for line in alternatives)
    option_count += sum(f"[ADR-{adr_id}-ALT-" in line for line in alternatives)
    if option_count < 2:
        raise AdrSchemaError(f"{path.name}: Alternatives must contain at least two options")
    evidence = sections[f"ADR-{adr_id}-EVIDENCE"]
    if not any(line.lstrip().startswith("- ") for line in evidence):
        raise AdrSchemaError(f"{path.name}: Evidence must contain an executable item")


def _visible_markdown(text: str) -> str:
    """Remove fenced code and HTML comments while preserving visible line order."""

    visible: list[str] = []
    active_fence_char: str | None = None
    active_fence_length = 0
    in_comment = False
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        newline = "\n" if raw_line.endswith(("\n", "\r")) else ""
        if active_fence_char is not None:
            closing = re.fullmatch(
                rf"[ \t]{{0,3}}{re.escape(active_fence_char)}"
                rf"{{{active_fence_length},}}[ \t]*",
                line,
            )
            visible.append(newline)
            if closing is not None:
                active_fence_char = None
                active_fence_length = 0
            continue

        uncommented, in_comment = _visible_html_fragments(line, in_comment)
        fence_match = None if in_comment else FENCE_OPEN_RE.match(uncommented)
        if fence_match is not None:
            fence = fence_match.group("fence")
            active_fence_char = fence[0]
            active_fence_length = len(fence)
            visible.append(newline)
            continue
        visible.append(f"{uncommented}{newline}")
    return "".join(visible)


def _visible_html_fragments(line: str, in_comment: bool) -> tuple[str, bool]:
    visible: list[str] = []
    cursor = 0
    while cursor < len(line):
        if in_comment:
            closing = line.find("-->", cursor)
            if closing < 0:
                return "".join(visible), True
            cursor = closing + 3
            in_comment = False
            continue
        opening = line.find("<!--", cursor)
        if opening < 0:
            visible.append(line[cursor:])
            break
        visible.append(line[cursor:opening])
        cursor = opening + 4
        in_comment = True
    return "".join(visible), in_comment

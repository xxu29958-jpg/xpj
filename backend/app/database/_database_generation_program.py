"""Read and validate the build-owned installed database generation program."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.database._c07_maintenance_plan import (
    C07_TARGET_REVISION,
    C07RevisionContract,
    build_c07_revision_contract,
)

PROGRAM_FILENAME = "DATABASE_GENERATION_PROGRAM.json"
PROGRAM_SCHEMA = "ticketbox-database-generation-program-v1"
BUILD_MANIFEST_FILENAME = "BUILD_PROVENANCE.json"
BUILD_MANIFEST_SCHEMA = 4
ALEMBIC_PROGRAM_ATTRIBUTE = "ticketbox_database_generation_program"
BASE_SOURCE = "base"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PROGRAM_KEYS = {"revisions", "schema", "source_revision", "target_revision"}
_REVISION_KEYS = {
    "context",
    "down_revision",
    "executor",
    "module_path",
    "module_sha256",
    "postcondition",
    "revision",
}
_EXECUTORS = {"c07_money_bigint_v1", "managed_postgres_v1"}


class DatabaseGenerationProgramError(RuntimeError):
    """The build-owned generation program is absent, changed, or unsupported."""


@dataclass(frozen=True)
class DatabaseGenerationRevision:
    revision: str
    down_revision: str | None
    executor: str
    module_path: Path
    module_sha256: str
    postcondition: str | None
    context: tuple[tuple[str, str], ...] | None


@dataclass(frozen=True)
class DatabaseGenerationC07Edge:
    source_revision: str
    target_revision: str
    revision_manifest: dict[str, object]
    revision_manifest_sha256: str
    revision: DatabaseGenerationRevision


@dataclass(frozen=True)
class DatabaseGenerationProgram:
    path: Path
    payload_sha256: str
    source_revision: str
    target_revision: str
    revisions: tuple[DatabaseGenerationRevision, ...]
    c07: DatabaseGenerationC07Edge

    def revision(self, revision_id: str) -> DatabaseGenerationRevision:
        match = next(
            (revision for revision in self.revisions if revision.revision == revision_id),
            None,
        )
        if match is None:
            raise DatabaseGenerationProgramError(
                "generation revision is outside the declared program"
            )
        return match

    def suffix(
        self,
        source_revision: str,
        target_revision: str,
    ) -> tuple[DatabaseGenerationRevision, ...]:
        if target_revision != self.target_revision:
            target_index = self.revisions.index(self.revision(target_revision))
        else:
            target_index = len(self.revisions) - 1
        source_index = (
            -1
            if source_revision == BASE_SOURCE
            else self.revisions.index(self.revision(source_revision))
        )
        if source_index >= target_index:
            if source_revision == target_revision:
                return ()
            raise DatabaseGenerationProgramError(
                "generation suffix is not a forward descendant"
            )
        suffix = self.revisions[source_index + 1 : target_index + 1]
        previous = None if source_revision == BASE_SOURCE else source_revision
        for revision in suffix:
            if revision.down_revision != previous:
                raise DatabaseGenerationProgramError(
                    "generation suffix is not one linear sequence"
                )
            previous = revision.revision
        return suffix


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_payload(path: Path, expected_sha256: str) -> dict[str, object]:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.name != PROGRAM_FILENAME
        or _SHA256.fullmatch(expected_sha256) is None
    ):
        raise DatabaseGenerationProgramError("generation program identity is invalid")
    try:
        payload = path.read_bytes()
        decoded = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatabaseGenerationProgramError("generation program cannot be read") from exc
    if (
        hashlib.sha256(payload).hexdigest() != expected_sha256
        or not isinstance(decoded, dict)
        or set(decoded) != _PROGRAM_KEYS
        or _canonical_json(decoded) != payload
        or decoded.get("schema") != PROGRAM_SCHEMA
        or decoded.get("source_revision") != BASE_SOURCE
        or not isinstance(decoded.get("target_revision"), str)
        or not decoded.get("target_revision")
    ):
        raise DatabaseGenerationProgramError(
            "generation program is not the canonical supported program"
        )
    return decoded


def _module_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str):
        raise DatabaseGenerationProgramError("generation module path is invalid")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or pure.parts[:2] != ("migrations", "versions")
    ):
        raise DatabaseGenerationProgramError("generation module path escapes payload")
    try:
        resolved = root.joinpath(*pure.parts).resolve(strict=True)
    except OSError as exc:
        raise DatabaseGenerationProgramError("generation module is unavailable") from exc
    if resolved.parent != (root / "migrations" / "versions").resolve(strict=True):
        raise DatabaseGenerationProgramError("generation module is outside versions")
    return resolved


def _revision(
    root: Path,
    raw: object,
    *,
    previous: str | None,
) -> tuple[DatabaseGenerationRevision, C07RevisionContract | None]:
    if not isinstance(raw, dict) or set(raw) != _REVISION_KEYS:
        raise DatabaseGenerationProgramError("generation revision shape is invalid")
    revision_id = raw.get("revision")
    executor = raw.get("executor")
    postcondition = raw.get("postcondition")
    module_sha256 = raw.get("module_sha256")
    if (
        not isinstance(revision_id, str)
        or not revision_id
        or raw.get("down_revision") != previous
        or executor not in _EXECUTORS
        or postcondition not in {None, "assert_postcondition"}
        or not isinstance(module_sha256, str)
        or _SHA256.fullmatch(module_sha256) is None
    ):
        raise DatabaseGenerationProgramError("generation revision contract is invalid")
    path = _module_path(root, raw.get("module_path"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != module_sha256:
        raise DatabaseGenerationProgramError("generation module bytes changed")
    c07_contract = None
    context = raw.get("context")
    if executor == "c07_money_bigint_v1":
        c07_contract = build_c07_revision_contract(
            module_path=path,
            module_sha256=module_sha256,
            source_revision=str(previous),
            target_revision=revision_id,
        )
        if context != c07_contract.context:
            raise DatabaseGenerationProgramError("generation C07 context changed")
    elif context is not None:
        raise DatabaseGenerationProgramError("generic revision has product context")
    return (
        DatabaseGenerationRevision(
            revision=revision_id,
            down_revision=previous,
            executor=str(executor),
            module_path=path,
            module_sha256=module_sha256,
            postcondition=postcondition,
            context=tuple(sorted(context.items())) if isinstance(context, dict) else None,
        ),
        c07_contract,
    )


def load_database_generation_program(
    *,
    path: Path,
    expected_sha256: str,
) -> DatabaseGenerationProgram:
    payload = _read_payload(path, expected_sha256)
    raw_revisions = payload.get("revisions")
    if not isinstance(raw_revisions, list) or not raw_revisions:
        raise DatabaseGenerationProgramError("generation program has no revisions")
    root = _backend_root().resolve(strict=True)
    revisions: list[DatabaseGenerationRevision] = []
    c07_entries: list[tuple[DatabaseGenerationRevision, C07RevisionContract]] = []
    previous: str | None = None
    for raw in raw_revisions:
        revision, c07_contract = _revision(root, raw, previous=previous)
        if any(existing.revision == revision.revision for existing in revisions):
            raise DatabaseGenerationProgramError("generation revision is duplicated")
        revisions.append(revision)
        if c07_contract is not None:
            c07_entries.append((revision, c07_contract))
        previous = revision.revision
    target = str(payload["target_revision"])
    if (
        previous != target
        or len(c07_entries) != 1
        or c07_entries[0][0].revision != C07_TARGET_REVISION
        or revisions[-1].postcondition != "assert_postcondition"
    ):
        raise DatabaseGenerationProgramError(
            "generation program does not terminate in one qualified head"
        )
    c07_revision, c07_contract = c07_entries[0]
    return DatabaseGenerationProgram(
        path=path,
        payload_sha256=expected_sha256,
        source_revision=BASE_SOURCE,
        target_revision=target,
        revisions=tuple(revisions),
        c07=DatabaseGenerationC07Edge(
            source_revision=str(c07_revision.down_revision),
            target_revision=c07_revision.revision,
            revision_manifest=c07_contract.revision_manifest,
            revision_manifest_sha256=c07_contract.revision_manifest_sha256,
            revision=c07_revision,
        ),
    )


def load_installed_database_generation_program() -> DatabaseGenerationProgram:
    """Load the frozen program through its co-shipped build manifest."""

    if not bool(getattr(sys, "frozen", False)):
        raise DatabaseGenerationProgramError(
            "installed generation program requires the frozen backend"
        )
    try:
        executable = Path(sys.executable).resolve(strict=True)
        root = executable.parent
        manifest_path = (root / BUILD_MANIFEST_FILENAME).resolve(strict=True)
        payload = json.loads(manifest_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatabaseGenerationProgramError(
            "installed build manifest is unavailable"
        ) from exc
    if (
        manifest_path.parent != root
        or not isinstance(payload, dict)
        or payload.get("schema_version") != BUILD_MANIFEST_SCHEMA
        or payload.get("artifact_type") != "ticketbox-frozen-backend"
        or not isinstance(payload.get("payload"), dict)
    ):
        raise DatabaseGenerationProgramError("installed build manifest is invalid")
    evidence = payload["payload"].get("database_generation_program")
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"path", "sha256", "size"}
        or evidence.get("path") != PROGRAM_FILENAME
        or not isinstance(evidence.get("size"), int)
        or isinstance(evidence.get("size"), bool)
        or int(evidence["size"]) <= 0
        or not isinstance(evidence.get("sha256"), str)
        or _SHA256.fullmatch(str(evidence["sha256"])) is None
    ):
        raise DatabaseGenerationProgramError(
            "installed generation program evidence is invalid"
        )
    try:
        program_path = (root / PROGRAM_FILENAME).resolve(strict=True)
        size = program_path.stat().st_size
    except OSError as exc:
        raise DatabaseGenerationProgramError(
            "installed generation program is unavailable"
        ) from exc
    if program_path.parent != root or size != int(evidence["size"]):
        raise DatabaseGenerationProgramError(
            "installed generation program size changed"
        )
    return load_database_generation_program(
        path=program_path,
        expected_sha256=str(evidence["sha256"]),
    )


__all__ = [
    "ALEMBIC_PROGRAM_ATTRIBUTE",
    "BASE_SOURCE",
    "DatabaseGenerationProgram",
    "DatabaseGenerationProgramError",
    "DatabaseGenerationRevision",
    "load_database_generation_program",
    "load_installed_database_generation_program",
]

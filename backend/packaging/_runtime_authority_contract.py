"""Installed Windows runtime authority and release-lineage verification."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from uuid import UUID

_FROZEN_HOST_AUTHORITY_KEYS = (
    "TICKETBOX_DATA_DIR",
    "TICKETBOX_INSTALLATION_ID",
    "TICKETBOX_DATASET_ID",
    "TICKETBOX_RELEASE_ID",
    "TICKETBOX_OWNER_RECOVERY_CHANNEL",
    "TICKETBOX_PORT",
)
_RELEASE_ID_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}\Z")
_BASE_ACTIVE_FIELDS = frozenset({
    "schema",
    "operation_id",
    "kind",
    "request_hash",
    "target_release_id",
    "data_root",
    "release_manifest_sha256",
    "backend_port",
    "phase",
    "no_return_point",
    "completed_step",
    "install_id",
    "dataset_id",
    "schema_revision",
    "health_attestation_key",
})
_UPGRADE_EXTRA_ACTIVE_FIELDS = frozenset({
    "expected_restore_epoch",
    "previous_release_id",
    "previous_release_manifest_sha256",
    "source_schema_revision",
    "backup_path",
    "backup_sha256",
    "business_writes_opened",
})


def _is_reparse_entry(entry: os.stat_result) -> bool:
    attributes = getattr(entry, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(entry.st_mode) or bool(attributes & reparse_attribute)


def _read_vnext_authority(
    path: Path,
    schema: str | tuple[str, ...],
    *,
    root: Path,
) -> dict[str, object] | None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("runtime authority escaped ProgramData") from exc
    cursor = root
    candidates = [root]
    for part in relative.parts:
        cursor /= part
        candidates.append(cursor)
    for candidate in candidates:
        try:
            entry = candidate.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise RuntimeError(f"{path.name} runtime authority is unreadable") from exc
        if _is_reparse_entry(entry):
            raise RuntimeError(f"{path.name} runtime authority contains a reparse point")
        expected_type = stat.S_ISREG if candidate == path else stat.S_ISDIR
        if not expected_type(entry.st_mode):
            raise RuntimeError(f"{path.name} runtime authority has an invalid path shape")
    try:
        encoded = path.read_bytes()
        if not 0 < len(encoded) <= 65536:
            raise RuntimeError(f"{path.name} runtime authority size is invalid")
        payload = json.loads(encoded.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{path.name} runtime authority is unreadable") from exc
    allowed_schemas = schema if isinstance(schema, tuple) else (schema,)
    if not isinstance(payload, dict) or payload.get("schema") not in allowed_schemas:
        raise RuntimeError(f"{path.name} runtime authority schema is unsupported")
    return payload


def _frozen_service_contract(data_dir: Path) -> tuple[str, str, str, int]:
    missing = [key for key in _FROZEN_HOST_AUTHORITY_KEYS if not (os.environ.get(key) or "").strip()]
    if missing:
        raise RuntimeError("frozen backend runtime authority environment is incomplete: " + ", ".join(missing))
    if os.environ["TICKETBOX_OWNER_RECOVERY_CHANNEL"].strip() != "managed_host":
        raise RuntimeError("frozen backend owner recovery channel is not managed_host")
    install_id = os.environ["TICKETBOX_INSTALLATION_ID"].strip()
    dataset_id = os.environ["TICKETBOX_DATASET_ID"].strip()
    release_id = os.environ["TICKETBOX_RELEASE_ID"].strip()
    try:
        if str(UUID(install_id)) != install_id or str(UUID(dataset_id)) != dataset_id:
            raise ValueError
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("frozen backend runtime identity is not canonical") from exc
    if re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}", release_id) is None:
        raise RuntimeError("frozen backend release identity is invalid")
    try:
        port = int(os.environ["TICKETBOX_PORT"])
    except ValueError as exc:
        raise RuntimeError("frozen backend port is invalid") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("frozen backend port is invalid")
    expected_data_dir = os.path.normcase(os.path.abspath(os.environ["TICKETBOX_DATA_DIR"]))
    if os.path.normcase(os.path.abspath(str(data_dir))) != expected_data_dir:
        raise RuntimeError("frozen backend data directory does not match its service environment")
    return install_id, dataset_id, release_id, port


def _read_temporal_authorities() -> tuple[dict[str, object] | None, dict[str, object] | None]:
    program_data = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    ticketbox_root = program_data / "Ticketbox"
    machine = ticketbox_root / "machine"
    active = _read_vnext_authority(
        machine / "operations" / "active.json",
        ("ticketbox-lifecycle-operation-v2", "ticketbox-lifecycle-operation-v3"),
        root=ticketbox_root,
    )
    if (
        active is not None
        and active.get("phase") != "committed"
        and active.get("schema") != "ticketbox-lifecycle-operation-v3"
        and active.get("kind") not in {"upgrade", "reinstall"}
    ):
        return None, active
    binding = _read_vnext_authority(
        machine / "installation.json",
        "ticketbox-installed-instance-v1",
        root=ticketbox_root,
    )
    if binding is None and active is None:
        raise RuntimeError("frozen backend requires Ticketbox runtime authority")
    return binding, active


def _valid_previous_release_id(binding: dict[str, object]) -> bool:
    previous = binding["previous_release_id"]
    if previous is None:
        return True
    return (
        isinstance(previous, str)
        and _RELEASE_ID_PATTERN.fullmatch(previous) is not None
        and previous != binding["active_release_id"]
    )


def _validate_closed_binding(binding: dict[str, object]) -> None:
    binding_fields = {
        "schema",
        "install_id",
        "dataset_id",
        "expected_restore_epoch",
        "data_root",
        "active_release_id",
        "previous_release_id",
        "release_manifest_sha256",
        "postgres_major",
        "pg_service_name",
        "backend_service_name",
        "pg_port",
        "backend_port",
        "health_attestation_key",
    }
    if set(binding) != binding_fields:
        raise RuntimeError("installation.json runtime authority fields are not closed")
    if (
        type(binding["expected_restore_epoch"]) is not int
        or binding["expected_restore_epoch"] < 0
        or not _valid_previous_release_id(binding)
    ):
        raise RuntimeError("installation.json has an invalid restore epoch or unsupported release transition")


def _closed_authorities(
    binding: dict[str, object] | None,
    active: dict[str, object] | None,
) -> list[dict[str, object]]:
    authorities: list[dict[str, object]] = []
    if binding is not None:
        _validate_closed_binding(binding)
    is_verify_candidate_with_binding = (
        active is not None
        and active.get("schema") == "ticketbox-lifecycle-operation-v2"
        and active.get("kind") in {"upgrade", "reinstall"}
        and active.get("phase") != "committed"
    )
    if binding is not None and not is_verify_candidate_with_binding:
        authorities.append(binding)
    if active is not None:
        if active.get("schema") == "ticketbox-lifecycle-operation-v3":
            from app.windows_connector_authority import require_connector_binding

            require_connector_binding(active, binding)
            return authorities
        _closed_active_authority(active, binding)
        authorities.append(active)
    return authorities


def _require_upgrade_backup_evidence(active: dict[str, object]) -> None:
    if (
        not isinstance(active["backup_path"], str)
        or not active["backup_path"]
        or not isinstance(active["backup_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", active["backup_sha256"]) is None
    ):
        raise RuntimeError("upgrade operation requires verified pre-upgrade backup evidence")


def _validate_upgrade_active_fields(active: dict[str, object]) -> tuple[str, str]:
    previous = active["previous_release_id"]
    if (
        not isinstance(previous, str)
        or _RELEASE_ID_PATTERN.fullmatch(previous) is None
        or previous == active["target_release_id"]
    ):
        raise RuntimeError("upgrade operation requires a valid previous release identity")
    previous_manifest = active["previous_release_manifest_sha256"]
    if (
        not isinstance(previous_manifest, str)
        or re.fullmatch(r"[0-9a-f]{64}", previous_manifest) is None
        or previous_manifest == active["release_manifest_sha256"]
    ):
        raise RuntimeError("upgrade operation requires a valid previous release manifest digest")
    if not isinstance(active["source_schema_revision"], str) or not active["source_schema_revision"]:
        raise RuntimeError("upgrade operation requires source schema revision")
    if type(active["business_writes_opened"]) is not bool:
        raise RuntimeError("upgrade operation requires boolean business_writes_opened")
    if active["phase"] != "committed" and active["business_writes_opened"] is not False:
        raise RuntimeError("uncommitted upgrade candidate cannot mark business writes opened")
    _require_upgrade_backup_evidence(active)
    return previous, previous_manifest


def _upgrade_binding_identity_matches(active: dict[str, object], binding: dict[str, object]) -> bool:
    binding_root = os.path.normcase(os.path.abspath(str(binding["data_root"])))
    active_root = os.path.normcase(os.path.abspath(str(active["data_root"])))
    return (
        binding["install_id"] == active["install_id"]
        and binding["dataset_id"] == active["dataset_id"]
        and binding_root == active_root
        and type(binding["backend_port"]) is int
        and binding["backend_port"] == active["backend_port"]
        and re.fullmatch(r"[0-9a-f]{64}", str(binding.get("release_manifest_sha256", ""))) is not None
        and re.fullmatch(r"[0-9a-f]{64}", str(binding.get("health_attestation_key", ""))) is not None
    )


def _validate_upgrade_binding_lineage(
    active: dict[str, object],
    binding: dict[str, object],
    *,
    previous: str,
    previous_manifest: str,
) -> None:
    if not _upgrade_binding_identity_matches(active, binding):
        raise RuntimeError("upgrade operation disagrees with installation binding")
    pre_publish = (
        binding["active_release_id"] == previous
        and binding["release_manifest_sha256"] == previous_manifest
    )
    post_publish = (
        binding["active_release_id"] == active["target_release_id"]
        and binding["previous_release_id"] == previous
        and binding["release_manifest_sha256"] == active["release_manifest_sha256"]
        and binding["health_attestation_key"] == active["health_attestation_key"]
    )
    if active["phase"] == "committed":
        if not post_publish:
            raise RuntimeError("committed upgrade disagrees with installation binding")
    elif not (pre_publish or post_publish):
        raise RuntimeError("upgrade candidate disagrees with installation binding release lineage")


def _closed_upgrade_active_authority(active: dict[str, object], binding: dict[str, object] | None) -> None:
    if binding is None:
        raise RuntimeError("upgrade operation requires existing installation binding")
    epoch = active["expected_restore_epoch"]
    if type(epoch) is not int or epoch < 0 or binding["expected_restore_epoch"] != epoch:
        raise RuntimeError("upgrade operation requires an exact non-negative restore epoch")
    previous, previous_manifest = _validate_upgrade_active_fields(active)
    _validate_upgrade_binding_lineage(
        active,
        binding,
        previous=previous,
        previous_manifest=previous_manifest,
    )


def _closed_reinstall_active_authority(active: dict[str, object], binding: dict[str, object] | None) -> None:
    if binding is None:
        raise RuntimeError("reinstall operation requires existing installation binding")
    epoch = active["expected_restore_epoch"]
    if type(epoch) is not int or epoch < 0 or binding["expected_restore_epoch"] != epoch:
        raise RuntimeError("reinstall operation requires an exact non-negative restore epoch")
    identity_match = (
        binding["install_id"] == active["install_id"]
        and binding["dataset_id"] == active["dataset_id"]
        and binding["active_release_id"] == active["target_release_id"]
        and binding["release_manifest_sha256"] == active["release_manifest_sha256"]
        and os.path.normcase(os.path.abspath(str(binding["data_root"])))
        == os.path.normcase(os.path.abspath(str(active["data_root"])))
        and type(binding["backend_port"]) is int
        and binding["backend_port"] == active["backend_port"]
    )
    if not identity_match:
        raise RuntimeError("reinstall operation disagrees with installation binding")


def _expected_active_fields(kind: object) -> frozenset[str]:
    if kind in {"restore", "reinstall"}:
        return _BASE_ACTIVE_FIELDS | {"expected_restore_epoch"}
    if kind == "upgrade":
        return _BASE_ACTIVE_FIELDS | _UPGRADE_EXTRA_ACTIVE_FIELDS
    return _BASE_ACTIVE_FIELDS


def _validate_active_kind_authority(
    kind: object,
    active: dict[str, object],
    binding: dict[str, object] | None,
) -> None:
    if kind == "restore":
        epoch = active["expected_restore_epoch"]
        if type(epoch) is not int or epoch <= 0 or (binding is not None and binding["expected_restore_epoch"] != epoch):
            raise RuntimeError("restore operation requires an exact positive target epoch")
    elif kind == "upgrade":
        _closed_upgrade_active_authority(active, binding)
    elif kind == "reinstall":
        _closed_reinstall_active_authority(active, binding)
    elif binding is not None and binding["expected_restore_epoch"] != 0:
        raise RuntimeError("Fresh cannot adopt a restored dataset")


def _closed_active_authority(active: dict[str, object], binding: dict[str, object] | None) -> None:
    kind = active.get("kind")
    if set(active) != _expected_active_fields(kind) or kind not in {"install", "restore", "upgrade", "reinstall"}:
        raise RuntimeError("active.json runtime authority fields are not closed")
    phase = active.get("phase")
    if phase not in {"data_ready", "release_activated", "committed"}:
        raise RuntimeError("active.json is not in a runtime-capable install phase")
    _validate_active_kind_authority(kind, active, binding)
    expected_step = {
        "data_ready": "scm" if kind in {"upgrade", "reinstall"} else "owner_claim",
        "release_activated": "health",
        "committed": "health",
    }[phase]
    if active.get("completed_step") != expected_step:
        raise RuntimeError("active.json runtime progress is not closed")
    if phase == "committed" and binding is None:
        raise RuntimeError("committed active operation requires installation binding")


def _assert_authority_contract(
    authorities: list[dict[str, object]],
    *,
    data_dir: Path,
    install_id: str,
    dataset_id: str,
    release_id: str,
    port: int,
) -> None:
    expected_root = os.path.normcase(os.path.abspath(str(data_dir.parent)))
    for payload in authorities:
        payload_release = payload.get("active_release_id", payload.get("target_release_id"))
        exact = (
            str(payload.get("install_id")) == install_id
            and str(payload.get("dataset_id")) == dataset_id
            and payload_release == release_id
            and os.path.normcase(os.path.abspath(str(payload.get("data_root", "")))) == expected_root
            and type(payload.get("backend_port")) is int
            and payload.get("backend_port") == port
            and re.fullmatch(r"[0-9a-f]{64}", str(payload.get("release_manifest_sha256", ""))) is not None
            and re.fullmatch(r"[0-9a-f]{64}", str(payload.get("health_attestation_key", ""))) is not None
        )
        if not exact:
            raise RuntimeError("Ticketbox runtime authority does not match the service contract")


def _assert_published_and_active_agree(
    binding: dict[str, object] | None,
    active: dict[str, object] | None,
) -> None:
    if binding is None or active is None:
        return
    if active.get("schema") == "ticketbox-lifecycle-operation-v3":
        return
    if active.get("kind") in {"upgrade", "reinstall"} and active.get("phase") != "committed":
        return
    for field in (
        "install_id",
        "dataset_id",
        "data_root",
        "release_manifest_sha256",
        "backend_port",
        "health_attestation_key",
    ):
        if binding[field] != active[field]:
            raise RuntimeError("published and active runtime authorities disagree")


def _export_runtime_authority_env(
    binding: dict[str, object] | None,
    active: dict[str, object] | None,
    authorities: list[dict[str, object]],
) -> None:
    epoch = binding["expected_restore_epoch"] if binding else active.get("expected_restore_epoch", 0)
    os.environ["TICKETBOX_EXPECTED_RESTORE_EPOCH"] = str(epoch)
    os.environ["TICKETBOX_RELEASE_MANIFEST_SHA256"] = str(authorities[0]["release_manifest_sha256"])
    uncommitted_active = active is not None and active["phase"] != "committed"
    os.environ["TICKETBOX_RESTORE_VERIFY_ONLY"] = (
        "1" if uncommitted_active and active["kind"] == "restore" else "0"
    )
    os.environ["TICKETBOX_UPGRADE_VERIFY_ONLY"] = (
        "1" if uncommitted_active and active["kind"] in {"upgrade", "reinstall"} else "0"
    )


def assert_vnext_runtime_authority(data_dir: Path) -> str:
    install_id, dataset_id, release_id, port = _frozen_service_contract(data_dir)
    executable = Path(os.path.abspath(sys.executable))
    try:
        executable_release = executable.parents[1].name
    except IndexError as exc:
        raise RuntimeError("frozen backend path does not match the installer layout") from exc
    if os.path.normcase(executable_release) != os.path.normcase(release_id):
        raise RuntimeError("frozen backend release environment does not match its executable")
    binding, active = _read_temporal_authorities()
    authorities = _closed_authorities(binding, active)
    _assert_authority_contract(
        authorities,
        data_dir=data_dir,
        install_id=install_id,
        dataset_id=dataset_id,
        release_id=release_id,
        port=port,
    )
    _assert_published_and_active_agree(binding, active)
    _export_runtime_authority_env(binding, active, authorities)
    return str(authorities[0]["health_attestation_key"])


def assert_runtime_data_root_authority(data_dir: Path) -> str | None:
    if getattr(sys, "frozen", False):
        return assert_vnext_runtime_authority(data_dir)
    return None

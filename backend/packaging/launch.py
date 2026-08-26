"""Frozen-EXE entry point for the Ticketbox backend.

PyInstaller bundles the read-only program (the ``app`` package, static assets,
Jinja templates, ``alembic.ini`` and ``migrations/``). The formal Windows
service receives the explicit ``TICKETBOX_DATA_DIR`` contract. The installed
instance binding or active fresh-install operation must match that path and
the exact immutable release. Only source/development invocation falls back to
``ticketbox-data/`` beside the program root. The database itself runs in the
installer-managed local PostgreSQL service. We set the data root BEFORE
importing ``app.*`` because :mod:`app.config` otherwise resolves paths against
PyInstaller's throwaway ``sys._MEIPASS`` extraction dir.

Run (frozen):   through the installer-validated Windows service contract
Run (dev):      python packaging/launch.py            (cwd = backend/)

The frozen build is windowed (``console=False``, ADR-0047 §8), so a running
service has no stdout/stderr. ``main()`` configures logging to a rotating file
under ``<data>/logs/`` BEFORE importing the app and tells uvicorn not to re-point
its handlers at ``sys.stdout`` — see :func:`_build_log_config`.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from argparse import ArgumentParser, Namespace
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, TextIO
from uuid import UUID

if not getattr(sys, "frozen", False):
    source_backend_root = str(Path(__file__).resolve().parents[1])
    if source_backend_root not in sys.path:
        sys.path.insert(0, source_backend_root)

from app.database_maintenance_runtime import (
    assert_maintenance_libpq_environment as _assert_maintenance_libpq_environment,
)
from app.database_maintenance_runtime import (
    load_standalone_database_module as _load_standalone_database_module,
)
from app.database_maintenance_runtime import (
    resolve_generation_program as _resolve_generation_program,
)

_FROZEN_HOST_AUTHORITY_KEYS = (
    "TICKETBOX_DATA_DIR",
    "TICKETBOX_INSTALLATION_ID",
    "TICKETBOX_DATASET_ID",
    "TICKETBOX_RELEASE_ID",
    "TICKETBOX_OWNER_RECOVERY_CHANNEL",
    "TICKETBOX_PORT",
)
_MANAGED_SCHEMA_UPGRADE_SWITCH = "--managed-schema-upgrade"
_FRESH_SCHEMA_UPGRADE_SWITCH = "--fresh-schema-upgrade"
_FRESH_OWNER_CLAIM_SWITCH = "--fresh-owner-claim"
_DATABASE_GENERATION_TARGET_VERIFY_SWITCH = "--database-generation-verify-target"
_GENERATION_PROGRAM_VALIDATE_SWITCH = "--validate-generation-program"
_DATABASE_GENERATION_HELPER_NAME = "ticketbox-database-maintenance.exe"
_MANAGED_SCHEMA_MODULE_NAME = "_ticketbox_managed_schema_upgrade"
_FRESH_SCHEMA_MODULE_NAME = "_ticketbox_fresh_schema_upgrade"
_DATABASE_GENERATION_TARGET_MODULE_NAME = "_ticketbox_database_generation_target"
_GENERATION_PROGRAM_VALIDATION_FIELDS = (
    "schema",
    "source_revision",
    "target_revision",
    "revision_count",
    "generation_program_sha256",
)
_FRESH_SCHEMA_RESULT_FIELDS = (
    "schema",
    "target_revision",
    "alembic_revision",
    "dataset_id",
    "client_generation",
    "result",
)
_FRESH_OWNER_RESULT_FIELDS = (
    "contract",
    "operation_id",
    "installation_id",
    "account_name",
    "ledger_id",
    "ledger_name",
    "device_name",
    "pairing_code",
    "pairing_expires_at",
    "pairing_derivation_index",
    "claim_generation",
)
_MANAGED_SCHEMA_RESULT_FIELDS = (
    "schema",
    "source_revision",
    "target_revision",
    "generation_program_sha256",
    "result",
    "alembic_revision",
)


def _bundle_dir() -> Path:
    """Directory the EXE was launched from (read-only program root when frozen).

    Frozen: the folder the user dropped the EXE in (``sys.executable``). Used
    ONLY to locate the *default* writable folder — never to write into when an
    installer/service has pre-set ``TICKETBOX_DATA_DIR`` (the EXE may sit in a
    read-only ``Program Files``). Dev: the backend/ project root (two levels up).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _is_database_generation_helper() -> bool:
    return getattr(sys, "frozen", False) and Path(sys.executable).name.lower() == _DATABASE_GENERATION_HELPER_NAME


def _add_generation_program_arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--generation-program-path", type=Path, required=True)
    parser.add_argument("--expected-generation-program-sha256", required=True)


def _parse_generation_program_validation_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(
        _GENERATION_PROGRAM_VALIDATE_SWITCH,
        action="store_true",
        required=True,
    )
    _add_generation_program_arguments(parser)
    return parser.parse_args(argv)


def _parse_managed_schema_upgrade_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(
        _MANAGED_SCHEMA_UPGRADE_SWITCH,
        action="store_true",
        required=True,
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    _add_generation_program_arguments(parser)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--generation-operation-id", required=True)
    return parser.parse_args(argv)


def _parse_fresh_schema_upgrade_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(
        _FRESH_SCHEMA_UPGRADE_SWITCH,
        action="store_true",
        required=True,
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--client-generation", required=True)
    parser.add_argument("--schema-min-compatible", required=True)
    parser.add_argument("--semantic-revision", required=True)
    parser.add_argument("--operation-id", required=True)
    return parser.parse_args(argv)


def _parse_fresh_owner_claim_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(_FRESH_OWNER_CLAIM_SWITCH, action="store_true", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--installation-id", required=True)
    return parser.parse_args(argv)


def _parse_database_generation_target_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(
        _DATABASE_GENERATION_TARGET_VERIFY_SWITCH,
        action="store_true",
        required=True,
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    _add_generation_program_arguments(parser)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--restore-attempt-id", default="")
    parser.add_argument("--target-revision", required=True)
    return parser.parse_args(argv)


def _load_managed_schema_upgrade_module() -> ModuleType:
    return _load_standalone_database_module(
        module_name=_MANAGED_SCHEMA_MODULE_NAME,
        filename="_managed_schema_upgrade.py",
        database_package_seam=True,
    )


def _load_fresh_schema_upgrade_module() -> ModuleType:
    return _load_standalone_database_module(
        module_name=_FRESH_SCHEMA_MODULE_NAME,
        filename="_fresh_schema_upgrade.py",
        database_package_seam=True,
    )


def _load_database_generation_target_module() -> ModuleType:
    return _load_standalone_database_module(
        module_name=_DATABASE_GENERATION_TARGET_MODULE_NAME,
        filename="_database_generation_target_verification.py",
        database_package_seam=True,
    )


def _run_generation_program_validation(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    """Validate the build-owned program without opening PostgreSQL."""

    args = _parse_generation_program_validation_args(argv)
    if input_stream is None:
        input_stream = sys.stdin.buffer
    if output_stream is None:
        output_stream = sys.stdout
    if input_stream is None or output_stream is None:
        raise RuntimeError("generation program validation requires redirected stdin/stdout")
    if input_stream.read(1) != b"":
        raise RuntimeError("generation program validation requires empty stdin")
    managed = _load_managed_schema_upgrade_module()
    result = managed.validate_database_generation_program(
        generation_program_path=_resolve_generation_program(args.generation_program_path),
        expected_generation_program_sha256=(args.expected_generation_program_sha256),
    )
    if tuple(result) != _GENERATION_PROGRAM_VALIDATION_FIELDS:
        raise RuntimeError("generation program validation returned an unsupported shape")
    output_stream.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    output_stream.flush()
    return 0


def _run_managed_schema_upgrade(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_managed_schema_upgrade_args(argv)
    if input_stream is None:
        input_stream = sys.stdin.buffer
    if output_stream is None:
        output_stream = sys.stdout
    if input_stream is None or output_stream is None:
        raise RuntimeError("managed schema upgrade requires redirected stdin/stdout")
    if input_stream.read(1) != b"":
        raise RuntimeError("managed schema upgrade requires empty stdin")

    _assert_maintenance_libpq_environment(args.pgpassfile)
    managed = _load_managed_schema_upgrade_module()
    result = managed.run_managed_schema_upgrade_action(
        database_url=args.database_url,
        pgpassfile=args.pgpassfile,
        generation_program_path=_resolve_generation_program(args.generation_program_path),
        expected_generation_program_sha256=(args.expected_generation_program_sha256),
        source_revision=args.source_revision,
        target_revision=args.target_revision,
        generation_operation_id=args.generation_operation_id,
    )
    if tuple(result) != _MANAGED_SCHEMA_RESULT_FIELDS:
        raise RuntimeError("managed schema upgrade returned an unsupported result shape")
    output_stream.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    output_stream.flush()
    return 0


def _run_fresh_schema_upgrade(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_fresh_schema_upgrade_args(argv)
    if input_stream is None:
        input_stream = sys.stdin.buffer
    if output_stream is None:
        output_stream = sys.stdout
    if input_stream is None or output_stream is None:
        raise RuntimeError("fresh schema upgrade requires redirected stdin/stdout")
    if input_stream.read(1) != b"":
        raise RuntimeError("fresh schema upgrade requires empty stdin")

    _assert_maintenance_libpq_environment(args.pgpassfile)
    module = _load_fresh_schema_upgrade_module()
    result = module.run_fresh_schema_upgrade_action(
        database_url=args.database_url,
        pgpassfile=args.pgpassfile,
        target_revision=args.target_revision,
        dataset_id=args.dataset_id,
        client_generation=args.client_generation,
        schema_min_compatible=args.schema_min_compatible,
        semantic_revision=args.semantic_revision,
        operation_id=args.operation_id,
    )
    if tuple(result) != _FRESH_SCHEMA_RESULT_FIELDS:
        raise RuntimeError("fresh schema upgrade returned an unsupported result shape")
    output_stream.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    output_stream.flush()
    return 0


def _run_fresh_owner_claim(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_fresh_owner_claim_args(argv)
    if input_stream is None:
        input_stream = sys.stdin.buffer
    if output_stream is None:
        output_stream = sys.stdout
    if input_stream is None or output_stream is None:
        raise RuntimeError("fresh owner claim requires redirected stdin/stdout")
    raw_secret = input_stream.read(257)
    if len(raw_secret) > 256:
        raise RuntimeError("fresh owner claim secret is too long")
    try:
        secret = raw_secret.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError("fresh owner claim secret is invalid") from exc
    if not 32 <= len(secret) <= 256 or any(character.isspace() for character in secret):
        raise RuntimeError("fresh owner claim secret is invalid")

    _assert_maintenance_libpq_environment(args.pgpassfile)
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.services.identity_service import bootstrap_installation_owner
    from app.services.secure_file import hold_installer_machine_secret_for_read

    with hold_installer_machine_secret_for_read(args.pgpassfile):
        engine = create_engine(
            args.database_url,
            connect_args={"connect_timeout": 10, "options": "-c timezone=utc"},
            pool_pre_ping=True,
            future=True,
        )
        try:
            with Session(engine, expire_on_commit=False) as db:
                db.execute(text("SET ROLE ticketbox_owner"))
                result = bootstrap_installation_owner(
                    db,
                    operation_id=args.operation_id,
                    installation_id=args.installation_id,
                    bootstrap_secret=secret,
                    account_name="我",
                    ledger_name="我的小票夹",
                    device_name="Windows 安装来源",
                    commit=False,
                )
                db.commit()
        finally:
            engine.dispose()
    payload = asdict(result)
    if tuple(payload) != _FRESH_OWNER_RESULT_FIELDS:
        raise RuntimeError("fresh owner claim returned an unsupported shape")
    output_stream.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    output_stream.flush()
    return 0


def _run_database_generation_target_verification(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_database_generation_target_args(argv)
    if input_stream is None:
        input_stream = sys.stdin.buffer
    if output_stream is None:
        output_stream = sys.stdout
    if input_stream is None or output_stream is None:
        raise RuntimeError("database generation target verification requires redirected IO")
    if input_stream.read(1) != b"":
        raise RuntimeError("database generation target verification requires empty stdin")
    _assert_maintenance_libpq_environment(args.pgpassfile)
    module = _load_database_generation_target_module()
    result = module.run_database_generation_target_verification_action(
        database_url=args.database_url,
        pgpassfile=args.pgpassfile,
        generation_program_path=_resolve_generation_program(args.generation_program_path),
        expected_generation_program_sha256=(args.expected_generation_program_sha256),
        operation_id=args.operation_id,
        database=args.database,
        restore_attempt_id=args.restore_attempt_id,
        target_revision=args.target_revision,
    )
    output_stream.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    output_stream.flush()
    return 0


def _resolve_writable_data_dir() -> Path:
    """Writable data root for files the backend *creates* (uploads, .env, backups).

    Honors the explicit installer/service ``TICKETBOX_DATA_DIR``. Frozen
    service startup additionally verifies this path against the installed
    instance binding or the active fresh-install operation. Only source mode
    may fall back to a ``ticketbox-data/`` folder beside the program root.
    """
    preset = os.environ.get("TICKETBOX_DATA_DIR", "").strip()
    if preset:
        return Path(os.path.abspath(preset))
    return _bundle_dir() / "ticketbox-data"



def _is_reparse_entry(entry: os.stat_result) -> bool:
    attributes = getattr(entry, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(entry.st_mode) or bool(attributes & reparse_attribute)


def _read_vnext_authority(
    path: Path,
    schema: str,
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
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise RuntimeError(f"{path.name} runtime authority schema is unsupported")
    return payload


def _frozen_service_contract(data_dir: Path) -> tuple[str, str, str, int]:
    missing = [
        key
        for key in _FROZEN_HOST_AUTHORITY_KEYS
        if not (os.environ.get(key) or "").strip()
    ]
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
        "ticketbox-lifecycle-operation-v2",
        root=ticketbox_root,
    )
    if active is not None and active.get("phase") != "committed":
        return None, active
    binding = _read_vnext_authority(
        machine / "installation.json",
        "ticketbox-installed-instance-v1",
        root=ticketbox_root,
    )
    if binding is None and active is None:
        raise RuntimeError("frozen backend requires Ticketbox runtime authority")
    return binding, active


def _closed_authorities(
    binding: dict[str, object] | None,
    active: dict[str, object] | None,
) -> list[dict[str, object]]:
    authorities: list[dict[str, object]] = []
    binding_fields = {
        "schema", "install_id", "dataset_id", "expected_restore_epoch", "data_root",
        "active_release_id", "previous_release_id", "release_manifest_sha256", "postgres_major",
        "pg_service_name", "backend_service_name", "pg_port", "backend_port",
    }
    active_fields = {
        "schema", "operation_id", "kind", "request_hash", "target_release_id", "data_root",
        "release_manifest_sha256", "backend_port", "phase", "no_return_point",
        "last_adapter_result", "install_id", "dataset_id", "schema_revision",
    }
    if binding is not None:
        if set(binding) != binding_fields:
            raise RuntimeError("installation.json runtime authority fields are not closed")
        if (
            type(binding["expected_restore_epoch"]) is not int
            or binding["expected_restore_epoch"] != 0
            or binding["previous_release_id"] is not None
        ):
            raise RuntimeError("installation.json is not a fresh-install binding")
        authorities.append(binding)
    if active is not None:
        if set(active) != active_fields or active.get("kind") != "install":
            raise RuntimeError("active.json runtime authority fields are not closed")
        phase = active.get("phase")
        if phase not in {"data_ready", "release_activated", "committed"}:
            raise RuntimeError("active.json is not in a runtime-capable install phase")
        if phase == "committed" and binding is None:
            raise RuntimeError("committed active operation requires installation binding")
        authorities.append(active)
    return authorities


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
        )
        if not exact:
            raise RuntimeError("Ticketbox runtime authority does not match the service contract")


def _assert_vnext_runtime_authority(data_dir: Path) -> None:
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
    if binding is not None and active is not None:
        for field in ("install_id", "dataset_id", "data_root", "release_manifest_sha256", "backend_port"):
            if binding[field] != active[field]:
                raise RuntimeError("published and active runtime authorities disagree")



def _assert_runtime_data_root_authority(data_dir: Path) -> None:
    if getattr(sys, "frozen", False):
        _assert_vnext_runtime_authority(data_dir)


def configure_environment() -> Path:
    """Point the app at a writable data dir; return that dir.

    Installed frozen builds require the complete host authority injected by the
    validated service contract. Source mode may omit that contract and resolve a
    local writable directory. A user-supplied ``<data>/.env`` then wins for the
    business/runtime values it sets (override=True), but never for host authority.
    ``DATABASE_URL`` is not defaulted here because PostgreSQL remains authoritative.
    """
    data_dir = _resolve_writable_data_dir()
    # These values are supplied by the host/service contract. The writable
    # app .env may configure business settings but cannot replace host identity.
    host_authority = {key: os.environ.get(key) for key in _FROZEN_HOST_AUTHORITY_KEYS}
    _assert_runtime_data_root_authority(data_dir)
    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    # Anchor app.config.DATA_ROOT here so writable files the backend *creates*
    # (Owner Console settings .env, PostgreSQL backups) persist in this folder
    # rather than the frozen build's throwaway _MEIPASS extraction dir. We
    # normalize the (possibly preset) value before the .env load and before
    # main() imports app.* so app.config reads the same resolved path we just
    # mkdir'd. This assignment is now idempotent with a preset (data_dir == the
    # resolved preset), so it normalizes rather than clobbering a service path.
    os.environ["TICKETBOX_DATA_DIR"] = str(data_dir)

    env_file = data_dir / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, encoding="utf-8-sig", override=True)

    os.environ["TICKETBOX_DATA_DIR"] = str(data_dir)
    for key, value in host_authority.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    # DATABASE_URL is intentionally not defaulted: the backend is PostgreSQL-only.
    # A user .env may set it; otherwise app.config supplies the local-PostgreSQL
    # default (the EXE assumes a local PostgreSQL service is installed).
    os.environ.setdefault("UPLOAD_DIR", str(data_dir / "uploads"))
    return data_dir



def _build_log_config(log_dir: Path, *, console: bool | None = None) -> dict:
    """Build a ``logging.config.dictConfig`` for the frozen backend.

    Everything — uvicorn's loggers plus the app/middleware loggers via the root
    logger — goes to a size-bounded rotating file under the writable data dir.
    This is what makes the windowed ``console=False`` service build (ADR-0047 §8)
    viable: there ``sys.stdout``/``sys.stderr`` are ``None``, so uvicorn's default
    config (which streams to ``ext://sys.stdout``) and Python's lastResort stderr
    handler would both crash on ``None.write`` — and a service with no console
    would die with no diagnostics. Routing to a file gives the service real logs.

    When a usable console exists (dev / source run) logs also echo to stdout.
    ``console`` defaults to whether ``sys.stdout`` is a real stream; tests pass it
    explicitly to exercise both shapes without mutating the global stream.
    """
    if console is None:
        console = sys.stdout is not None
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers: dict[str, dict] = {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(log_dir / "backend.log"),
            # Bounded so a long-running self-hosted service can't grow logs
            # without limit (ENGINEERING_RULES §12): ~5 MB × 3 backups.
            "maxBytes": 5_000_000,
            "backupCount": 3,
            "encoding": "utf-8",
            "formatter": "plain",
            "level": "INFO",
        }
    }
    active = ["file"]
    if console:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "plain",
            "level": "INFO",
        }
        active.append("console")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"},
        },
        "handlers": handlers,
        # Root catches the app + middleware loggers (they have no own handlers).
        "root": {"handlers": active, "level": "INFO"},
        "loggers": {
            # uvicorn ships its own handlers; repoint them at ours and stop
            # propagation so its lines aren't also re-emitted via the root logger.
            "uvicorn": {"handlers": active, "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": active, "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": active, "level": "INFO", "propagate": False},
        },
    }


def _initialize_installed_runtime_settings(data_dir: Path) -> None:
    """Create the service-owned initial projection before importing the app."""

    from app.services.runtime_settings_store import (
        RuntimeSettingsProjection,
        initialize_runtime_settings,
    )

    settings_dir = data_dir / "runtime-settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    initialize_runtime_settings(
        settings_dir / "runtime-settings.json",
        RuntimeSettingsProjection("", False),
        service_owned=True,
    )


def main() -> int | None:
    arguments = sys.argv[1:]
    maintenance_switches = [
        switch
        for switch in (
            _MANAGED_SCHEMA_UPGRADE_SWITCH,
            _FRESH_SCHEMA_UPGRADE_SWITCH,
            _FRESH_OWNER_CLAIM_SWITCH,
            _DATABASE_GENERATION_TARGET_VERIFY_SWITCH,
            _GENERATION_PROGRAM_VALIDATE_SWITCH,
        )
        if switch in arguments
    ]
    if len(maintenance_switches) > 1:
        raise RuntimeError("database generation helper accepts exactly one mode")
    if maintenance_switches:
        if getattr(sys, "frozen", False) and not _is_database_generation_helper():
            raise RuntimeError("database generation requires the dedicated frozen helper")
        if maintenance_switches[0] == _MANAGED_SCHEMA_UPGRADE_SWITCH:
            return _run_managed_schema_upgrade(arguments)
        if maintenance_switches[0] == _FRESH_SCHEMA_UPGRADE_SWITCH:
            return _run_fresh_schema_upgrade(arguments)
        if maintenance_switches[0] == _FRESH_OWNER_CLAIM_SWITCH:
            return _run_fresh_owner_claim(arguments)
        if maintenance_switches[0] == _DATABASE_GENERATION_TARGET_VERIFY_SWITCH:
            return _run_database_generation_target_verification(arguments)
        return _run_generation_program_validation(arguments)
    if _is_database_generation_helper():
        raise RuntimeError("the dedicated database generation helper requires an explicit mode")

    import logging.config

    data_dir = configure_environment()
    # Configure logging to a rotating file under the data dir BEFORE importing the
    # app, so the console=False service build (sys.stdout/stderr None) never falls
    # through to logging's lastResort stderr handler, and startup/import-time
    # diagnostics are captured. See _build_log_config + ADR-0047 §8.
    logging.config.dictConfig(_build_log_config(data_dir / "logs"))
    if getattr(sys, "frozen", False):
        _initialize_installed_runtime_settings(data_dir)
    host = os.getenv("TICKETBOX_HOST", "127.0.0.1")
    port = int(os.getenv("TICKETBOX_PORT", "8000"))

    # Import the app object directly (not the "app.main:app" string form):
    # uvicorn's string import re-resolves the module via importlib, which is
    # unreliable in a frozen bundle and masks real import errors as
    # "Could not import module". Passing the object also makes any failure in
    # the app's import graph surface here with a real traceback.
    import uvicorn

    from app.main import app as fastapi_app

    # console=False (ADR-0047 §8 service build) gives a windowed PyInstaller
    # process no stdout/stderr — ``sys.stdout`` is None and ``.write`` would
    # raise. Guard so the same entrypoint is safe in both the console build and
    # the windowed-service build (the file log records startup either way).
    if sys.stdout is not None:
        print(f"Ticketbox backend  ·  data: {data_dir}  ·  http://{host}:{port}", flush=True)

    # ADR-0047 §Confirmation: keep a bounded drain for service builds. Slice 2-D
    # verified the current console=False Shawl service build does not receive
    # Ctrl-C/SIGINT and falls back to Shawl's stop-timeout kill; the app writes
    # no business state during lifespan shutdown, while PG keeps durability.
    shutdown_timeout = int(os.getenv("TICKETBOX_SHUTDOWN_TIMEOUT_SECONDS", "25"))
    uvicorn.run(
        fastapi_app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        # Logging is already configured above (file + optional console). Pass
        # None so uvicorn does NOT re-apply its default config, which streams to
        # ext://sys.stdout and would crash under console=False.
        log_config=None,
        timeout_graceful_shutdown=shutdown_timeout,
    )


if __name__ == "__main__":
    import multiprocessing

    # PyInstaller hardening (ADR-0047 §8): a frozen build that ever spawns a
    # child process (e.g. a future multi-worker uvicorn) would otherwise
    # re-execute the bootloader and recursively launch the app. No-op today
    # (workers=1, app object passed directly), required before any spawn lands.
    multiprocessing.freeze_support()
    exit_code = main()
    if exit_code is not None:
        raise SystemExit(exit_code)

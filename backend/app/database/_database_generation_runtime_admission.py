"""Read the sole installed database-generation CURRENT and its live DB binding."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database._lifecycle import DatabaseMigrationPreflightError
from app.services.secure_file import hold_system_runtime_projection_for_read

_CURRENT_DIRECTORY = "database-generation-runtime"
_CURRENT_FILE = "current-generation.json"
_MACHINE_DIRECTORY = "Ticketbox"
_COMMON_PROGRAM_FILES = 0x002B
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")
_BINDING_KEY = "database_generation_binding"
_ENVELOPE_FIELDS = ("schema", "kind", "payload_sha256", "payload")
_CURRENT_FIELD_ORDER = (
    "schema operation_id installation_id intent_sha256 candidate_sha256 "
    "committed_revision generation_program_sha256 database_binding_sha256 "
    "terminal_state_sha256 expected_predecessor_sha256"
)
_BINDING_FIELD_ORDER = (
    "schema operation_id installation_id intent_sha256 source_binding_sha256 "
    "target_revision generation_program_sha256 cluster_system_identifier database_oid "
    "database_name runtime_role logical_server_id logical_data_generation "
    "execution_authority_sha256 role_authority_sha256 runtime_acl_sha256 "
    "post_migration_writer_fence_sha256 target_recovery_evidence_sha256"
)
_BINDING_SHA_FIELD_ORDER = (
    "source_binding_sha256 generation_program_sha256 execution_authority_sha256 "
    "role_authority_sha256 runtime_acl_sha256 post_migration_writer_fence_sha256 "
    "target_recovery_evidence_sha256"
)
_LIVE_DATABASE_QUERY = text(
    """
    SELECT control.system_identifier::text, database.oid::bigint,
           current_database()::text,
           session_user::text,
           (SELECT value FROM public.app_meta WHERE key = 'server_id'),
           (SELECT value FROM public.app_meta WHERE key = 'data_generation'),
            COALESCE((SELECT role.rolcanlogin AND role.rolinherit
                       AND NOT role.rolsuper AND NOT role.rolcreatedb
                       AND NOT role.rolcreaterole AND NOT role.rolreplication
                       AND NOT role.rolbypassrls AND role.rolconnlimit = -1
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = session_user
            ), false),
            COALESCE((SELECT COALESCE(role.rolconfig, ARRAY[]::text[]) =
                             ARRAY['search_path=pg_catalog, public']::text[]
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = session_user
            ), false),
            NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
               WHERE granted.rolname = session_user
                  OR member.rolname = session_user
           ),
           COALESCE(pg_catalog.pg_get_userbyid(database.datdba) = 'ticketbox_owner', false),
            COALESCE((SELECT pg_catalog.pg_get_userbyid(namespace.nspowner) = 'ticketbox_owner'
                FROM pg_catalog.pg_namespace AS namespace WHERE namespace.nspname = 'public'
            ), false),
           pg_catalog.has_database_privilege(session_user, current_database(), 'CONNECT'),
           NOT pg_catalog.has_database_privilege(session_user, current_database(), 'CREATE'),
           NOT pg_catalog.has_database_privilege(session_user, current_database(), 'TEMPORARY'),
           pg_catalog.has_schema_privilege(session_user, 'public', 'USAGE'),
           NOT pg_catalog.has_schema_privilege(session_user, 'public', 'CREATE'),
            NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
               WHERE namespace.nspname = 'public'
                 AND pg_catalog.pg_get_userbyid(relation.relowner) = session_user
               UNION ALL
               SELECT 1 FROM pg_catalog.pg_proc AS routine
               JOIN pg_catalog.pg_namespace AS namespace
                 ON namespace.oid = routine.pronamespace
               WHERE namespace.nspname = 'public'
                 AND pg_catalog.pg_get_userbyid(routine.proowner) = session_user
               UNION ALL
               SELECT 1 FROM pg_catalog.pg_type AS type
               JOIN pg_catalog.pg_namespace AS namespace
                 ON namespace.oid = type.typnamespace
               WHERE namespace.nspname = 'public'
                  AND pg_catalog.pg_get_userbyid(type.typowner) = session_user
            ),
            COALESCE((SELECT NOT role.rolcanlogin AND NOT role.rolinherit
                       AND NOT role.rolsuper AND NOT role.rolcreatedb
                       AND NOT role.rolcreaterole AND NOT role.rolreplication
                       AND NOT role.rolbypassrls AND role.rolconnlimit = -1
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = 'ticketbox_owner'
            ), false)
            AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
                WHERE granted.rolname = 'ticketbox_owner' OR member.rolname = 'ticketbox_owner'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_stat_activity WHERE usename = 'ticketbox_owner' AND pid <> pg_backend_pid()
            ),
            COALESCE((SELECT NOT role.rolcanlogin AND NOT role.rolinherit
                       AND NOT role.rolsuper AND NOT role.rolcreatedb
                       AND NOT role.rolcreaterole AND NOT role.rolreplication
                       AND NOT role.rolbypassrls AND role.rolconnlimit = 1
                FROM pg_catalog.pg_roles AS role WHERE role.rolname = 'ticketbox_migrator'
            ), false)
            AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
                WHERE granted.rolname = 'ticketbox_migrator' OR member.rolname = 'ticketbox_migrator'
            ) AND NOT pg_catalog.has_database_privilege(
                'ticketbox_migrator', current_database(), 'CONNECT')
            AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_stat_activity WHERE usename = 'ticketbox_migrator' AND pid <> pg_backend_pid()
           )
    FROM pg_catalog.pg_database AS database
    CROSS JOIN pg_catalog.pg_control_system() AS control
    WHERE database.datname = current_database()
    """
)
_RUNTIME_ACL_EVIDENCE_QUERY = text(
    """
    WITH acl_rows AS (
        SELECT 'database'::text AS kind,
               database.datname AS object_name,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC') AS grantee,
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_database AS database,
             LATERAL pg_catalog.aclexplode(
                 COALESCE(
                     database.datacl,
                    pg_catalog.acldefault('d'::"char", database.datdba)
                 )
             ) AS acl
        WHERE database.datname = current_database()
        UNION ALL
        SELECT 'schema', namespace.nspname,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC'),
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_namespace AS namespace,
             LATERAL pg_catalog.aclexplode(
                 COALESCE(
                     namespace.nspacl,
                    pg_catalog.acldefault('n'::"char", namespace.nspowner)
                 )
             ) AS acl
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT CASE WHEN relation.relkind = 'S' THEN 'sequence' ELSE 'relation' END,
               namespace.nspname || '.' || relation.relname,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC'),
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                relation.relacl,
                pg_catalog.acldefault(
                    CASE WHEN relation.relkind = 'S' THEN 'S'::"char"
                         ELSE 'r'::"char"
                    END,
                    relation.relowner
                )
            )
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
        UNION ALL
        SELECT 'routine', namespace.nspname || '.' ||
               routine.oid::regprocedure::text,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC'),
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                routine.proacl,
                pg_catalog.acldefault('f'::"char", routine.proowner)
            )
        ) AS acl
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT 'routine', namespace.nspname || '.' ||
               routine.oid::regprocedure::text,
               COALESCE(pg_catalog.pg_get_userbyid(acl.grantee), 'PUBLIC'),
               acl.privilege_type,
               acl.is_grantable
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(
                routine.proacl,
                pg_catalog.acldefault('f'::"char", routine.proowner)
            )
        ) AS acl
        WHERE routine.oid = 'pg_catalog.pg_control_system()'::regprocedure
    )
    SELECT kind || E'\t' || object_name || E'\t' || grantee || E'\t' ||
           privilege_type || E'\t' || is_grantable::text
    FROM acl_rows
    WHERE NOT (
        kind = 'database'
        AND object_name = current_database()
        AND grantee IN ('ticketbox_runtime', 'ticketbox_migrator')
        AND privilege_type = 'CONNECT'
        AND NOT is_grantable
    )
    ORDER BY kind, object_name, grantee, privilege_type, is_grantable
    """
)


class DatabaseGenerationAdmissionError(RuntimeError):
    """Installed runtime CURRENT or its live database binding is not exact."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _runtime_acl_sha256(evidence: tuple[str, ...]) -> str:
    return _sha256("\n".join(evidence))


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise DatabaseGenerationAdmissionError(f"{label} must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise DatabaseGenerationAdmissionError(f"{label} must be a UUID") from exc
    if parsed.int == 0 or str(parsed) != value:
        raise DatabaseGenerationAdmissionError(f"{label} must be a canonical UUID")
    return value


def _lower_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DatabaseGenerationAdmissionError(f"{label} must be a lower SHA-256")
    return value


def _positive_decimal(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise DatabaseGenerationAdmissionError(f"{label} must be a positive decimal")
    return value


def _database_oid(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 0xFFFFFFFF:
        raise DatabaseGenerationAdmissionError(f"{label} must be a positive database OID")
    return value


def _common_program_files() -> Path:
    if os.name != "nt":
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT is Windows-only")
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.shell32.SHGetFolderPathW(  # type: ignore[attr-defined]
        None,
        _COMMON_PROGRAM_FILES,
        None,
        0,
        buffer,
    )
    if result != 0 or not buffer.value:
        raise DatabaseGenerationAdmissionError("Common Program Files is unavailable")
    return Path(os.path.abspath(buffer.value))


def database_generation_runtime_current_path() -> Path:
    return _common_program_files() / _MACHINE_DIRECTORY / _CURRENT_DIRECTORY / _CURRENT_FILE


def _read_current(path: Path) -> tuple[dict[str, object], str]:
    try:
        with hold_system_runtime_projection_for_read(path) as protected:
            raw = protected.read_bytes().decode("utf-8")
        envelope = json.loads(raw)
    except (OSError, PermissionError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT is unavailable") from exc
    if (
        raw.startswith("\ufeff")
        or "\r" in raw
        or "\n" in raw
        or not isinstance(envelope, dict)
        or tuple(envelope) != _ENVELOPE_FIELDS
        or raw != _canonical_json(envelope)
        or envelope.get("schema") != "ticketbox-database-generation-envelope-v1"
        or envelope.get("kind") != "current"
        or not isinstance(envelope.get("payload"), dict)
    ):
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT is not canonical")
    payload = envelope["payload"]
    assert isinstance(payload, dict)
    if " ".join(payload) != _CURRENT_FIELD_ORDER:
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT fields are not closed")
    payload_sha = _lower_sha(envelope.get("payload_sha256"), "CURRENT payload")
    if _sha256(_canonical_json(payload)) != payload_sha:
        raise DatabaseGenerationAdmissionError("installed runtime CURRENT digest changed")
    return payload, payload_sha


def _validate_current(current: dict[str, object], program: object) -> tuple[str, str, str, str, str, str]:
    operation_id = _canonical_uuid(current["operation_id"], "CURRENT operation_id")
    installation_id = _canonical_uuid(current["installation_id"], "CURRENT installation_id")
    intent_sha = _lower_sha(current["intent_sha256"], "CURRENT intent")
    _lower_sha(current["candidate_sha256"], "CURRENT candidate")
    binding_sha = _lower_sha(current["database_binding_sha256"], "CURRENT database binding")
    program_sha = _lower_sha(current["generation_program_sha256"], "CURRENT generation program")
    _lower_sha(current["terminal_state_sha256"], "CURRENT terminal state")
    revision = current["committed_revision"]
    if (
        not isinstance(revision, str)
        or _REVISION.fullmatch(revision) is None
        or current["schema"] != "ticketbox-current-database-generation-v1"
        or current["expected_predecessor_sha256"] != ""
        or revision != getattr(program, "target_revision", None)
        or program_sha != getattr(program, "payload_sha256", None)
    ):
        raise DatabaseGenerationAdmissionError("CURRENT does not bind the installed program")
    return (
        operation_id,
        installation_id,
        intent_sha,
        binding_sha,
        program_sha,
        revision,
    )


def _observe_live_database(
    engine: object,
) -> tuple[object, tuple[str, ...], object, str]:
    try:
        with engine.connect() as connection:  # type: ignore[union-attr]
            binding_json = connection.scalar(
                text("SELECT value FROM public.app_meta WHERE key = :key"),
                {"key": _BINDING_KEY},
            )
            revisions = tuple(
                str(value) for value in connection.scalars(text("SELECT version_num FROM public.alembic_version"))
            )
            live_identity = connection.execute(_LIVE_DATABASE_QUERY).one()
            runtime_acl_evidence = tuple(str(value) for value in connection.scalars(_RUNTIME_ACL_EVIDENCE_QUERY))
    except (OSError, RuntimeError, SQLAlchemyError, TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError("live database binding is unavailable") from exc
    return (
        binding_json,
        revisions,
        live_identity,
        _runtime_acl_sha256(runtime_acl_evidence),
    )


def _load_binding(binding_json: object, binding_sha: str) -> dict[str, object]:
    if not isinstance(binding_json, str) or _sha256(binding_json) != binding_sha:
        raise DatabaseGenerationAdmissionError("live database binding digest changed")
    try:
        binding = json.loads(binding_json)
    except json.JSONDecodeError as exc:
        raise DatabaseGenerationAdmissionError("live database binding is not JSON") from exc
    if not isinstance(binding, dict):
        raise DatabaseGenerationAdmissionError("live database binding is not an object")
    return binding


def _assert_runtime_capability(values: tuple[object, ...]) -> None:
    if len(values) != 13 or any(value is not True for value in values):
        raise DatabaseGenerationAdmissionError("live runtime capability is not DML-only")


def _assert_live_binding(
    binding: dict[str, object],
    binding_json: str,
    revisions: tuple[str, ...],
    live_identity: object,
    live_runtime_acl_sha256: str,
    *,
    operation_id: str,
    installation_id: str,
    intent_sha: str,
    program_sha: str,
    revision: str,
) -> None:
    try:
        (
            live_cluster_identifier,
            live_database_oid,
            live_database_name,
            live_session_user,
            live_server_id,
            live_data_generation,
            *live_runtime_capabilities,
        ) = live_identity  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError("live database identity is incomplete") from exc
    try:
        canonical_live_database_oid = _database_oid(int(live_database_oid), "live database OID")
    except (TypeError, ValueError) as exc:
        raise DatabaseGenerationAdmissionError("live database OID is invalid") from exc
    _assert_runtime_capability(tuple(live_runtime_capabilities))
    if (
        " ".join(binding) != _BINDING_FIELD_ORDER
        or binding_json != _canonical_json(binding)
        or binding["schema"] != "ticketbox-database-generation-database-binding-v1"
        or binding["operation_id"] != operation_id
        or binding["installation_id"] != installation_id
        or binding["intent_sha256"] != intent_sha
        or binding["target_revision"] != revision
        or binding["generation_program_sha256"] != program_sha
        or revisions != (revision,)
        or _positive_decimal(
            binding["cluster_system_identifier"],
            "database binding cluster identity",
        )
        != str(live_cluster_identifier)
        or _database_oid(binding["database_oid"], "database binding database OID") != canonical_live_database_oid
        or binding["database_name"] != live_database_name
        or binding["runtime_role"] != live_session_user
        or _lower_sha(
            binding["runtime_acl_sha256"],
            "database binding runtime ACL",
        )
        != live_runtime_acl_sha256
        or _canonical_uuid(binding["logical_server_id"], "database binding server_id")
        != _canonical_uuid(live_server_id, "live server_id")
        or _canonical_uuid(
            binding["logical_data_generation"],
            "database binding data_generation",
        )
        != _canonical_uuid(live_data_generation, "live data_generation")
    ):
        raise DatabaseGenerationAdmissionError("live database binding does not match the sole CURRENT")
    if binding["database_name"] != "ticketbox" or binding["runtime_role"] != "ticketbox_runtime":
        raise DatabaseGenerationAdmissionError("database binding runtime target is not closed")
    for field in _BINDING_SHA_FIELD_ORDER.split():
        _lower_sha(binding[field], f"database binding {field}")


def assert_database_generation_runtime_admission(
    engine: object,
    program: object,
    *,
    current_path: Path | None = None,
) -> None:
    current, _current_sha = _read_current(current_path or database_generation_runtime_current_path())
    current_contract = _validate_current(current, program)
    binding_json, revisions, live_identity, live_runtime_acl_sha256 = _observe_live_database(engine)
    binding = _load_binding(binding_json, current_contract[3])
    assert isinstance(binding_json, str)
    _assert_live_binding(
        binding,
        binding_json,
        revisions,
        live_identity,
        live_runtime_acl_sha256,
        operation_id=current_contract[0],
        installation_id=current_contract[1],
        intent_sha=current_contract[2],
        program_sha=current_contract[4],
        revision=current_contract[5],
    )


def assert_database_generation_startup_ready(engine: object, program: object) -> None:
    """Translate the installed CURRENT admission contract into startup refusal."""

    try:
        assert_database_generation_runtime_admission(engine, program)
    except DatabaseGenerationAdmissionError as exc:
        raise DatabaseMigrationPreflightError(
            f"拒绝开放数据库 writer:Generation CURRENT 或 live binding 未完成({exc})。"
        ) from exc


__all__ = [
    "DatabaseGenerationAdmissionError",
    "assert_database_generation_runtime_admission",
    "assert_database_generation_startup_ready",
    "database_generation_runtime_current_path",
]

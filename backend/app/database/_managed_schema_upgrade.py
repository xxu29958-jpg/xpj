"""Frozen release-schema plan and short-lived migrator execution.

The Windows installer owns this path.  It authenticates as the retired-on-idle
``ticketbox_migrator`` role, assumes ``ticketbox_owner`` only inside the DDL
transaction, and never exposes schema authority to the long-lived backend.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.alembic_revision_contract import assert_linear_descendant_chain
from app.database._c07_contract import MIGRATION_LEASE_LABEL
from app.database._c07_production_connection import (
    _create_production_engine,
    _temporary_pgpass_environment,
    _validated_migrator_url,
    _validated_pgpass_path,
)
from app.database._c07_production_contract_types import (
    DATABASE_NAME,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
)

PLAN_SCHEMA = "ticketbox-managed-schema-plan-v1"
RESULT_SCHEMA = "ticketbox-managed-schema-upgrade-result-v1"
MANIFEST_SCHEMA = "ticketbox-managed-schema-manifest-v1"


class ManagedSchemaUpgradeError(RuntimeError):
    """The frozen helper cannot prove or execute the release migration."""


@dataclass(frozen=True)
class ManagedSchemaPlan:
    source_revision: str
    target_revision: str
    revisions: tuple[dict[str, str], ...]
    manifest_sha256: str


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _load_plan(source_revision: str) -> ManagedSchemaPlan:
    root = _backend_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    try:
        scripts = ScriptDirectory.from_config(config)
        heads = tuple(scripts.get_heads())
        if len(heads) != 1 or scripts.get_revision(source_revision) is None:
            raise ManagedSchemaUpgradeError(
                "managed schema source/head is outside the frozen graph"
            )
        target_revision = heads[0]
        assert_linear_descendant_chain(
            scripts,
            target_revision=source_revision,
            head_revision=target_revision,
            error_factory=ManagedSchemaUpgradeError,
            error_message="managed schema path is not a single linear descendant chain",
        )
        forward = tuple(
            reversed(tuple(scripts.iterate_revisions(target_revision, source_revision)))
        )
    except ManagedSchemaUpgradeError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ManagedSchemaUpgradeError(
            "managed schema graph cannot be resolved"
        ) from exc

    versions_root = (root / "migrations" / "versions").resolve()
    previous = source_revision
    revisions: list[dict[str, str]] = []
    for revision in forward:
        path = Path(str(revision.path)).resolve()
        if (
            path.parent != versions_root
            or not path.is_file()
            or revision.down_revision != previous
            or revision.dependencies is not None
        ):
            raise ManagedSchemaUpgradeError(
                "managed schema revision identity is not a linear packaged file"
            )
        revisions.append(
            {
                "revision": str(revision.revision),
                "down_revision": previous,
                "module_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        previous = str(revision.revision)
    if previous != target_revision:
        raise ManagedSchemaUpgradeError(
            "managed schema plan did not terminate at the frozen head"
        )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "source_revision": source_revision,
        "target_revision": target_revision,
        "revisions": revisions,
    }
    return ManagedSchemaPlan(
        source_revision=source_revision,
        target_revision=target_revision,
        revisions=tuple(revisions),
        manifest_sha256=hashlib.sha256(_canonical_json(manifest)).hexdigest(),
    )


def get_managed_schema_plan(*, source_revision: str) -> dict[str, object]:
    plan = _load_plan(source_revision)
    return {
        "schema": PLAN_SCHEMA,
        "source_revision": plan.source_revision,
        "target_revision": plan.target_revision,
        "upgrade_required": bool(plan.revisions),
        "revision_count": len(plan.revisions),
        "revision_manifest_sha256": plan.manifest_sha256,
    }


def _current_revision(connection: Any) -> str:
    revisions = tuple(
        str(value)
        for value in connection.scalars(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
    )
    if len(revisions) != 1:
        raise ManagedSchemaUpgradeError(
            "managed schema database must expose exactly one revision"
        )
    return revisions[0]


def _load_revision(revision: dict[str, str]) -> Any:
    # The graph is authoritative for filenames; resolve it again and bind the
    # physical module to the manifest hash immediately before execution.
    config = Config(str(_backend_root() / "alembic.ini"))
    config.set_main_option(
        "script_location", str(_backend_root() / "migrations")
    )
    script = ScriptDirectory.from_config(config).get_revision(revision["revision"])
    if script is None:
        raise ManagedSchemaUpgradeError("managed schema revision disappeared")
    path = Path(str(script.path)).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != revision["module_sha256"]:
        raise ManagedSchemaUpgradeError("managed schema revision changed after planning")
    spec = importlib.util.spec_from_file_location(
        f"_ticketbox_managed_schema_{revision['revision']}",
        path,
    )
    if spec is None or spec.loader is None:
        raise ManagedSchemaUpgradeError("managed schema revision cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (
        getattr(module, "revision", None) != revision["revision"]
        or getattr(module, "down_revision", None) != revision["down_revision"]
        or not callable(getattr(module, "upgrade", None))
    ):
        raise ManagedSchemaUpgradeError("managed schema revision metadata drifted")
    return module


def _run_plan(connection: Any, plan: ManagedSchemaPlan) -> str:
    principal = tuple(
        str(value)
        for value in connection.execute(
            text("SELECT session_user, current_user, current_database()")
        ).one()
    )
    if principal != (MIGRATOR_ROLE, MIGRATOR_ROLE, DATABASE_NAME):
        raise ManagedSchemaUpgradeError(
            "managed schema connection is not the dedicated migrator"
        )
    acquired = connection.scalar(
        text(
            "SELECT pg_try_advisory_xact_lock("
            "hashtext(current_database()), hashtext(:label))"
        ),
        {"label": MIGRATION_LEASE_LABEL},
    )
    if acquired is not True:
        raise ManagedSchemaUpgradeError("managed schema migration lease is busy")
    other_clients = connection.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datid = (SELECT oid FROM pg_database "
            "WHERE datname = current_database()) "
            "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
        )
    )
    if int(other_clients or 0) != 0:
        raise ManagedSchemaUpgradeError(
            "managed schema migration observed another client writer"
        )
    connection.execute(text(f'SET LOCAL ROLE "{SCHEMA_OWNER_ROLE}"'))
    effective = tuple(
        str(value)
        for value in connection.execute(
            text("SELECT session_user, current_user")
        ).one()
    )
    if effective != (MIGRATOR_ROLE, SCHEMA_OWNER_ROLE):
        raise ManagedSchemaUpgradeError(
            "managed schema migrator cannot assume the schema owner"
        )

    current = _current_revision(connection)
    if current == plan.target_revision:
        return "target_observed_after_interruption"
    if current != plan.source_revision:
        raise ManagedSchemaUpgradeError(
            "managed schema live revision is outside the frozen release path"
        )

    operations = Operations(MigrationContext.configure(connection))
    for revision in plan.revisions:
        module = _load_revision(revision)
        module.op = operations
        module.upgrade()
        advanced = connection.scalar(
            text(
                "UPDATE alembic_version SET version_num = :target "
                "WHERE version_num = :source RETURNING version_num"
            ),
            {
                "source": revision["down_revision"],
                "target": revision["revision"],
            },
        )
        if advanced != revision["revision"]:
            raise ManagedSchemaUpgradeError(
                "managed schema revision marker did not advance atomically"
            )
    if _current_revision(connection) != plan.target_revision:
        raise ManagedSchemaUpgradeError(
            "managed schema migration did not reach the frozen head"
        )
    return "target_committed"


def run_managed_schema_upgrade_action(
    *,
    database_url: str,
    pgpassfile: Path,
    source_revision: str,
    target_revision: str,
    expected_revision_manifest_sha256: str,
) -> dict[str, object]:
    plan = _load_plan(source_revision)
    if (
        target_revision != plan.target_revision
        or expected_revision_manifest_sha256 != plan.manifest_sha256
        or not plan.revisions
    ):
        raise ManagedSchemaUpgradeError(
            "managed schema CLI does not match the frozen release plan"
        )
    parsed_url = _validated_migrator_url(database_url)
    protected_pgpass = _validated_pgpass_path(pgpassfile)
    engine: Engine | None = None
    try:
        with _temporary_pgpass_environment(protected_pgpass):
            engine = _create_production_engine(parsed_url)
            with engine.begin() as connection:
                result = _run_plan(connection, plan)
    except ManagedSchemaUpgradeError:
        raise
    except SQLAlchemyError as exc:
        raise ManagedSchemaUpgradeError(
            "managed schema PostgreSQL action failed"
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()
    return {
        "schema": RESULT_SCHEMA,
        "source_revision": plan.source_revision,
        "target_revision": plan.target_revision,
        "revision_manifest_sha256": plan.manifest_sha256,
        "result": result,
        "alembic_revision": plan.target_revision,
    }


__all__ = [
    "ManagedSchemaUpgradeError",
    "get_managed_schema_plan",
    "run_managed_schema_upgrade_action",
]

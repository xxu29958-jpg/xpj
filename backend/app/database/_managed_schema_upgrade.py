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
from alembic.script import ScriptDirectory

from app.alembic_revision_contract import assert_linear_descendant_chain
from app.database._managed_postgres_contract import (
    DATABASE_NAME,
    MIGRATION_LEASE_LABEL,
    MIGRATOR_ROLE,
    SCHEMA_OWNER_ROLE,
)
from app.database._managed_postgres_migration_runtime import (
    ManagedPostgresMigrationRuntimeError,
    ManagedPostgresMigrationRuntimeV1,
    ManagedPostgresRuntimeContractV1,
)

PLAN_SCHEMA = "ticketbox-managed-schema-plan-v1"
RESULT_SCHEMA = "ticketbox-managed-schema-upgrade-result-v1"
MANIFEST_SCHEMA = "ticketbox-managed-schema-manifest-v1"
_TRANSACTION_TIMEOUT_MS = 20 * 60 * 1000
_ALEMBIC_JSON_PROTOCOL_ATTRIBUTE = "ticketbox_managed_migration_json_protocol_v1"


class ManagedSchemaUpgradeError(RuntimeError):
    """The frozen helper cannot prove or execute the release migration."""


@dataclass(frozen=True)
class ManagedSchemaPlan:
    config: Config
    source_revision: str
    target_revision: str
    revisions: tuple[dict[str, str], ...]
    postcondition_revision: dict[str, str]
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


def _postcondition_revision(
    scripts: ScriptDirectory,
    *,
    target_revision: str,
    versions_root: Path,
    revisions: list[dict[str, str]],
) -> dict[str, str]:
    if revisions:
        return revisions[-1]
    target = scripts.get_revision(target_revision)
    if target is None or not isinstance(target.down_revision, str):
        raise ManagedSchemaUpgradeError(
            "managed schema target cannot bind its release postcondition"
        )
    target_path = Path(str(target.path)).resolve()
    if (
        target_path.parent != versions_root
        or not target_path.is_file()
        or target.dependencies is not None
    ):
        raise ManagedSchemaUpgradeError(
            "managed schema target postcondition is not a packaged file"
        )
    return {
        "revision": target_revision,
        "down_revision": target.down_revision,
        "module_sha256": hashlib.sha256(target_path.read_bytes()).hexdigest(),
    }


def _load_plan(source_revision: str) -> ManagedSchemaPlan:
    root = _backend_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes[_ALEMBIC_JSON_PROTOCOL_ATTRIBUTE] = True
    try:
        scripts = ScriptDirectory.from_config(config)
        heads = tuple(scripts.get_heads())
        if len(heads) != 1 or scripts.get_revision(source_revision) is None:
            raise ManagedSchemaUpgradeError("managed schema source/head is outside the frozen graph")
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
        raise ManagedSchemaUpgradeError("managed schema graph cannot be resolved") from exc

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
    postcondition_revision = _postcondition_revision(
        scripts,
        target_revision=target_revision,
        versions_root=versions_root,
        revisions=revisions,
    )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "source_revision": source_revision,
        "target_revision": target_revision,
        "revisions": revisions,
    }
    if not revisions:
        # An already-at-head recovery still executes the release postcondition.
        # Bind that module into the otherwise-empty manifest so plan/action
        # handoff cannot silently select different verification code.
        manifest["target_postcondition"] = postcondition_revision
    return ManagedSchemaPlan(
        config=config,
        source_revision=source_revision,
        target_revision=target_revision,
        revisions=tuple(revisions),
        postcondition_revision=postcondition_revision,
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
        or not callable(getattr(module, "assert_postcondition", None))
    ):
        raise ManagedSchemaUpgradeError("managed schema revision metadata drifted")
    return module


def _target_postcondition(plan: ManagedSchemaPlan) -> Any:
    return _load_revision(plan.postcondition_revision).assert_postcondition


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
    ):
        raise ManagedSchemaUpgradeError(
            "managed schema CLI does not match the frozen release plan"
        )
    runtime = ManagedPostgresMigrationRuntimeV1(
        ManagedPostgresRuntimeContractV1(
            database_name=DATABASE_NAME,
            migrator_role=MIGRATOR_ROLE,
            schema_owner_role=SCHEMA_OWNER_ROLE,
            lease_label=MIGRATION_LEASE_LABEL,
            transaction_timeout_ms=_TRANSACTION_TIMEOUT_MS,
        )
    )
    try:
        result = runtime.run(
            database_url=database_url,
            pgpassfile=pgpassfile,
            alembic_config=plan.config,
            source_revision=plan.source_revision,
            target_revision=plan.target_revision,
            verify_postcondition=_target_postcondition(plan),
        )
    except ManagedPostgresMigrationRuntimeError as exc:
        raise ManagedSchemaUpgradeError(
            "managed schema PostgreSQL action failed"
        ) from exc
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

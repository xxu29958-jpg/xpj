"""Exact packaged Alembic plan for the ADR-0073 C07 release edge.

The installer uses this module before it opens PostgreSQL.  It intentionally
recognizes one transition only: ``20260722_0001`` to ``20260729_0001``.  A
later packaged head must remain a single linear descendant and cannot widen
the transition or resources attested by this authority.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError, RevisionError
from alembic.util.exc import CommandError

from app.alembic_revision_contract import assert_linear_descendant_chain
from app.money_contract import (
    MONEY_COLUMNS_V1,
    MONEY_REMOVED_LEGACY_CHECKS_V1,
)

MAINTENANCE_PLAN_SCHEMA = "ticketbox-c07-maintenance-plan-v2"
REVISION_MANIFEST_SCHEMA = "ticketbox-c07-revision-manifest-v1"
C07_GRAPH_BASE_REVISION = "20260524_0001"
C07_SOURCE_REVISION = "20260722_0001"
C07_TARGET_REVISION = "20260729_0001"
C07_OPERATION_KIND = "c07_money_minor_bigint_v1"
ISOLATED_MODE = "isolated_replay"
C07_ALEMBIC_PROTOCOL_ATTRIBUTE = "ticketbox_c07_json_protocol_v1"

_PLAN_FIELDS = (
    "schema",
    "operation_kind",
    "source_revision",
    "target_revision",
    "upgrade_required",
    "revision_manifest",
    "revision_manifest_sha256",
)
_MANIFEST_FIELDS = (
    "schema",
    "operation_kind",
    "source_revision",
    "target_revision",
    "revisions",
)
_REVISION_FIELDS = (
    "revision",
    "down_revision",
    "module_sha256",
    "transactionality",
    "reversibility",
    "downgrade_guard",
    "resources",
    "asset_recovery",
)


class C07MaintenanceUpgradeError(RuntimeError):
    """The frozen helper cannot prove the exact C07 maintenance contract."""


@dataclass(frozen=True)
class MaintenancePlan:
    config: Config
    source_revision: str
    target_revision: str
    revision_manifest: dict[str, object]
    revision_manifest_sha256: str


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )


def _revision_resources() -> list[str]:
    resources = [
        f"column:{contract.table}.{contract.column}:type=int8"
        for contract in MONEY_COLUMNS_V1
    ]
    resources.extend(
        f"constraint:{check.table}.{check.name}:present_validated"
        for contract in MONEY_COLUMNS_V1
        for check in contract.checks
    )
    resources.extend(
        f"constraint:{check.table}.{check.name}:absent"
        for check in MONEY_REMOVED_LEGACY_CHECKS_V1
    )
    resources.extend(
        (
            "meta:money_contract_phase=c07_money_minor_bigint_v1",
            "meta:money_c07_ceremony_id:present",
            "meta:money_c07_lifecycle_state:present",
        )
    )
    if len(resources) != len(set(resources)):
        raise AssertionError("C07 revision resources are not unique")
    return resources


def _assert_forward_only_downgrade(path: Path) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        raise C07MaintenanceUpgradeError(
            "C07 migration source cannot be parsed"
        ) from None
    downgrade = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "downgrade"
        ),
        None,
    )
    if (
        downgrade is None
        or len(downgrade.body) != 1
        or not isinstance(downgrade.body[0], ast.Raise)
    ):
        raise C07MaintenanceUpgradeError(
            "C07 downgrade is not an explicit forward-only guard"
        )
    rendered = ast.unparse(downgrade.body[0]).lower()
    if "runtimeerror" not in rendered or "forward-only" not in rendered:
        raise C07MaintenanceUpgradeError(
            "C07 downgrade guard wording has drifted"
        )


def _load_exact_plan() -> MaintenancePlan:
    root = _backend_root()
    ini_path = root / "alembic.ini"
    migrations_path = root / "migrations"
    config = Config(str(ini_path))
    config.attributes[C07_ALEMBIC_PROTOCOL_ATTRIBUTE] = True
    config.set_main_option("script_location", str(migrations_path))
    try:
        scripts = ScriptDirectory.from_config(config)
        bases = tuple(scripts.get_bases())
        heads = tuple(scripts.get_heads())
        source = scripts.get_revision(C07_SOURCE_REVISION)
        target = scripts.get_revision(C07_TARGET_REVISION)
    except (
        CommandError,
        ResolutionError,
        RevisionError,
        OSError,
        KeyError,
        ValueError,
    ):
        raise C07MaintenanceUpgradeError(
            "C07 packaged Alembic graph cannot be resolved"
        ) from None
    if (
        bases != (C07_GRAPH_BASE_REVISION,)
        or len(heads) != 1
        or source is None
        or target is None
        or source.revision != C07_SOURCE_REVISION
        or target.revision != C07_TARGET_REVISION
        or target.down_revision != C07_SOURCE_REVISION
        or target.dependencies is not None
        or set(source.nextrev) != {C07_TARGET_REVISION}
    ):
        raise C07MaintenanceUpgradeError(
            "C07 packaged Alembic graph differs from the exact release edge"
        )
    assert_linear_descendant_chain(
        scripts, target_revision=C07_TARGET_REVISION, head_revision=heads[0],
        error_factory=C07MaintenanceUpgradeError,
        error_message="C07 packaged Alembic graph differs from the exact release edge",
    )
    path = Path(str(target.path)).resolve()
    expected_parent = (migrations_path / "versions").resolve()
    if path.parent != expected_parent or not path.is_file():
        raise C07MaintenanceUpgradeError(
            "C07 migration source is outside the packaged versions directory"
        )
    _assert_forward_only_downgrade(path)
    revision: dict[str, object] = {
        "revision": C07_TARGET_REVISION,
        "down_revision": C07_SOURCE_REVISION,
        "module_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "transactionality": "postgresql_single_transaction",
        "reversibility": "forward_only",
        "downgrade_guard": "raises_runtime_error_before_ddl",
        "resources": _revision_resources(),
        "asset_recovery": "same_generation_database_and_assets",
    }
    if tuple(revision) != _REVISION_FIELDS:
        raise AssertionError("C07 revision manifest field order changed")
    manifest: dict[str, object] = {
        "schema": REVISION_MANIFEST_SCHEMA,
        "operation_kind": C07_OPERATION_KIND,
        "source_revision": C07_SOURCE_REVISION,
        "target_revision": C07_TARGET_REVISION,
        "revisions": [revision],
    }
    if tuple(manifest) != _MANIFEST_FIELDS:
        raise AssertionError("C07 manifest field order changed")
    return MaintenancePlan(
        config=config,
        source_revision=C07_SOURCE_REVISION,
        target_revision=C07_TARGET_REVISION,
        revision_manifest=manifest,
        revision_manifest_sha256=hashlib.sha256(
            _canonical_json(manifest).encode("utf-8")
        ).hexdigest(),
    )


def load_exact_maintenance_plan(
    *,
    source_revision: str,
    target_revision: str,
) -> MaintenancePlan:
    if (
        source_revision != C07_SOURCE_REVISION
        or target_revision != C07_TARGET_REVISION
    ):
        raise C07MaintenanceUpgradeError(
            "C07 maintenance accepts only the frozen source/target edge"
        )
    return _load_exact_plan()


def get_installed_maintenance_plan(
    *, source_revision: str
) -> dict[str, object]:
    """Return the one release plan used by fresh and legacy C07 adoption."""

    plan = load_exact_maintenance_plan(
        source_revision=source_revision,
        target_revision=C07_TARGET_REVISION,
    )
    result: dict[str, object] = {
        "schema": MAINTENANCE_PLAN_SCHEMA,
        "operation_kind": C07_OPERATION_KIND,
        "source_revision": plan.source_revision,
        "target_revision": plan.target_revision,
        "upgrade_required": True,
        "revision_manifest": plan.revision_manifest,
        "revision_manifest_sha256": plan.revision_manifest_sha256,
    }
    if tuple(result) != _PLAN_FIELDS:
        raise AssertionError("C07 maintenance plan field order changed")
    return result


__all__ = [
    "C07_OPERATION_KIND",
    "C07_SOURCE_REVISION",
    "C07_TARGET_REVISION",
    "ISOLATED_MODE",
    "C07MaintenanceUpgradeError",
    "MaintenancePlan",
    "get_installed_maintenance_plan",
    "load_exact_maintenance_plan",
]

"""Pure C07 revision contract used by build and runtime program validation."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.money_contract import MONEY_COLUMNS_V1, MONEY_REMOVED_LEGACY_CHECKS_V1

REVISION_MANIFEST_SCHEMA = "ticketbox-c07-revision-manifest-v1"
C07_GRAPH_BASE_REVISION = "20260524_0001"
C07_SOURCE_REVISION = "20260722_0001"
C07_TARGET_REVISION = "20260729_0001"
C07_OPERATION_KIND = "c07_money_minor_bigint_v1"
ISOLATED_MODE = "isolated_replay"

_C07_CONTEXT_CONSTANTS = (
    "_CEREMONY_MODE_GUC",
    "_CEREMONY_ID_GUC",
    "_STATEMENT_TIMEOUT_GUC",
    "_MANAGED_MODE",
)


class C07MaintenanceUpgradeError(RuntimeError):
    """The declared C07 revision does not match the product contract."""


@dataclass(frozen=True)
class C07RevisionContract:
    context: dict[str, str]
    revision_manifest: dict[str, object]
    revision_manifest_sha256: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


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


def _module_constants(tree: ast.Module) -> dict[str, str]:
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else (node.target,)
        )
        if isinstance(target, ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def build_c07_revision_contract(
    *,
    module_path: Path,
    module_sha256: str,
    source_revision: str,
    target_revision: str,
) -> C07RevisionContract:
    if (
        source_revision != C07_SOURCE_REVISION
        or target_revision != C07_TARGET_REVISION
        or len(module_sha256) != 64
        or any(character not in "0123456789abcdef" for character in module_sha256)
    ):
        raise C07MaintenanceUpgradeError("C07 revision identity is invalid")
    try:
        payload = module_path.read_bytes()
        tree = ast.parse(payload, filename=str(module_path))
    except (OSError, SyntaxError, ValueError) as exc:
        raise C07MaintenanceUpgradeError("C07 migration source cannot be parsed") from exc
    if hashlib.sha256(payload).hexdigest() != module_sha256:
        raise C07MaintenanceUpgradeError("C07 migration bytes changed")

    downgrade = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "downgrade"
        ),
        None,
    )
    if downgrade is None or len(downgrade.body) != 1 or not isinstance(
        downgrade.body[0], ast.Raise
    ):
        raise C07MaintenanceUpgradeError("C07 downgrade is not forward-only")
    rendered = ast.unparse(downgrade.body[0]).lower()
    if "runtimeerror" not in rendered or "forward-only" not in rendered:
        raise C07MaintenanceUpgradeError("C07 downgrade guard wording drifted")

    constants = _module_constants(tree)
    if set(_C07_CONTEXT_CONSTANTS) - set(constants):
        raise C07MaintenanceUpgradeError("C07 ceremony contract is incomplete")
    context = {
        "ceremony_id_guc": constants["_CEREMONY_ID_GUC"],
        "ceremony_mode_guc": constants["_CEREMONY_MODE_GUC"],
        "kind": "c07_ceremony_v1",
        "ceremony_mode": constants["_MANAGED_MODE"],
        "statement_timeout_guc": constants["_STATEMENT_TIMEOUT_GUC"],
    }
    if any(not value or "\x00" in value for value in context.values()):
        raise C07MaintenanceUpgradeError("C07 ceremony contract is invalid")
    revision: dict[str, object] = {
        "revision": target_revision,
        "down_revision": source_revision,
        "module_sha256": module_sha256,
        "transactionality": "postgresql_single_transaction",
        "reversibility": "forward_only",
        "downgrade_guard": "raises_runtime_error_before_ddl",
        "resources": _revision_resources(),
        "asset_recovery": "same_generation_database_and_assets",
    }
    manifest: dict[str, object] = {
        "schema": REVISION_MANIFEST_SCHEMA,
        "operation_kind": C07_OPERATION_KIND,
        "source_revision": source_revision,
        "target_revision": target_revision,
        "revisions": [revision],
    }
    manifest_sha256 = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    context["revision_manifest_sha256"] = manifest_sha256
    context["source_revision"] = source_revision
    return C07RevisionContract(context, manifest, manifest_sha256)


__all__ = [
    "C07_OPERATION_KIND",
    "C07_SOURCE_REVISION",
    "C07_TARGET_REVISION",
    "C07MaintenanceUpgradeError",
    "C07RevisionContract",
    "ISOLATED_MODE",
    "build_c07_revision_contract",
]

"""Fail-closed unit contracts for the ADR-0073 C07 ceremony."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config

import app.database._c07_host_freeze_evidence as host_freeze_evidence
import app.database._c07_storage as c07_storage
from app.database import (
    _c07_ceremony as c07,
)
from app.database import (
    _c07_ceremony_document as ceremony_document,
)
from app.database import (
    _c07_commit_reconciliation as commit_reconciliation,
)
from app.services.secure_file import (
    hold_protected_file_for_read,
    write_protected_file_exclusive,
)
from tests._infra.c07_ceremony_fixtures import (
    windows_freeze_envelope as _windows_freeze_envelope,
)

_CEREMONY_ID = "66d65d05-c93a-4fde-b544-5578b6bfa18f"
_RELEASE_IDENTITY = "a" * 40
_AUTHORITY_DIGEST = "b" * 64


def test_ceremony_facade_preserves_focused_module_entrypoints() -> None:
    assert c07._assert_asset_recovery_contract is ceremony_document._assert_asset_recovery_contract  # noqa: SLF001
    assert c07._classify_staged_receipt_commit is commit_reconciliation._classify_staged_receipt_commit  # noqa: SLF001


def _proof_payload(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "schema": host_freeze_evidence.ISOLATED_FREEZE_SCHEMA,
        "operation_id": _CEREMONY_ID,
        "release_identity": _RELEASE_IDENTITY,
        "mode": "isolated_test",
        "authority_digest": _AUTHORITY_DIGEST,
        "lifecycle_lock_held": True,
        "backend_service_state": "stopped",
        "runtime_process_count": 0,
        "listener_pid_count": 0,
        "coordinator_pid": 4242,
        "recorded_at_utc": now.isoformat().replace("+00:00", "Z"),
        "expires_at_utc": (now + timedelta(minutes=5))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    payload.update(overrides)
    return payload


def _write_proof(path: Path, payload: dict[str, object]) -> None:
    write_protected_file_exclusive(path, c07._canonical_json(payload))  # noqa: SLF001


def test_host_freeze_proof_is_canonical_protected_and_process_bound(
    tmp_path: Path,
) -> None:
    path = tmp_path / "writer-freeze.json"
    _write_proof(path, _proof_payload())

    evidence = c07.read_host_freeze_evidence(
        path,
        expected_release_identity=_RELEASE_IDENTITY,
        expected_parent_pid=4242,
        allow_isolated_test=True,
    )

    assert evidence.operation_id == _CEREMONY_ID
    assert evidence.authority_digest == _AUTHORITY_DIGEST
    assert evidence.evidence_sha256 == c07._sha256_file(path)  # noqa: SLF001
    assert c07._identity_evidence is c07_storage._identity_evidence  # noqa: SLF001


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"lifecycle_lock_held": False}, "stopped writer"),
        ({"backend_service_state": "running"}, "stopped writer"),
        ({"runtime_process_count": 1}, "stopped writer"),
        ({"listener_pid_count": 1}, "stopped writer"),
        ({"coordinator_pid": 4243}, "coordinator process"),
        ({"operation_id": str("0" * 8 + "-0000-0000-0000-000000000000")}, "non-zero"),
        (
            {
                "recorded_at_utc": (
                    datetime.now(UTC) - timedelta(hours=1)
                ).isoformat().replace("+00:00", "Z"),
                "expires_at_utc": (
                    datetime.now(UTC) - timedelta(minutes=1)
                ).isoformat().replace("+00:00", "Z"),
            },
            "stale",
        ),
    ],
)
def test_host_freeze_proof_rejects_unproven_authority(
    tmp_path: Path,
    overrides: dict[str, object],
    error: str,
) -> None:
    path = tmp_path / "writer-freeze.json"
    _write_proof(path, _proof_payload(**overrides))

    with pytest.raises(c07.C07CeremonyError, match=error):
        c07.read_host_freeze_evidence(
            path,
            expected_release_identity=_RELEASE_IDENTITY,
            expected_parent_pid=4242,
            allow_isolated_test=True,
        )


def test_isolated_test_proof_is_never_authorized_in_production(
    tmp_path: Path,
) -> None:
    path = tmp_path / "writer-freeze.json"
    _write_proof(path, _proof_payload())

    with pytest.raises(c07.C07CeremonyError, match="lifecycle authority layout"):
        c07.read_host_freeze_evidence(
            path,
            expected_release_identity=_RELEASE_IDENTITY,
            expected_parent_pid=4242,
        )


@pytest.mark.parametrize("binding_suffix", ["", "-binding-3"])
def test_windows_ceremony_is_blocked_until_same_generation_assets_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_suffix: str,
) -> None:
    lifecycle = tmp_path / "c07-lifecycle"
    lifecycle.mkdir()
    path = lifecycle / (
        f"operation-{_CEREMONY_ID}-freeze-proof{binding_suffix}.json"
    )
    release_identity, envelope = _windows_freeze_envelope()
    write_protected_file_exclusive(path, envelope)
    monkeypatch.setattr(
        host_freeze_evidence,
        "hold_system_authority_file_for_read",
        hold_protected_file_for_read,
    )
    process_times = {4242: (10, 20), 4243: (30, 40)}
    monkeypatch.setattr(
        host_freeze_evidence,
        "windows_process_start_filetime",
        process_times.__getitem__,
    )
    evidence = c07.read_host_freeze_evidence(
        path,
        expected_release_identity=release_identity,
        expected_parent_pid=4242,
    )
    assert evidence.operation_id == _CEREMONY_ID
    assert evidence.heartbeat_sequence == 7
    assert evidence.database_binding_sha256 == "C" * 64
    with pytest.raises(c07.C07CeremonyError, match="ADR-0071"):
        c07._assert_asset_recovery_contract(evidence)  # noqa: SLF001


def test_windows_freeze_path_accepts_shared_canonical_operation_guid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical_operation_id = "1493b3d9-3721-0e51-0255-58aba5ba6e99"
    lifecycle = tmp_path / "c07-lifecycle"
    lifecycle.mkdir()
    path = lifecycle / (
        f"operation-{historical_operation_id}-freeze-proof-binding-1.json"
    )
    release_identity, envelope = _windows_freeze_envelope(
        operation_id=historical_operation_id
    )
    write_protected_file_exclusive(path, envelope)
    monkeypatch.setattr(
        host_freeze_evidence,
        "hold_system_authority_file_for_read",
        hold_protected_file_for_read,
    )
    process_times = {4242: (10, 20), 4243: (30, 40)}
    monkeypatch.setattr(
        host_freeze_evidence,
        "windows_process_start_filetime",
        process_times.__getitem__,
    )

    evidence = c07.read_host_freeze_evidence(
        path,
        expected_release_identity=release_identity,
        expected_parent_pid=4242,
    )

    assert evidence.operation_id == historical_operation_id


def _apply_writer_capability_drift(
    payload: dict[str, object],
    drift: str,
) -> None:
    count_fields = {
        "prepared_transaction": "database_prepared_transaction_count",
        "prepared_capability": "database_max_prepared_transactions",
        "logical_subscription": "database_logical_subscription_count",
        "logical_apply_worker": "database_logical_apply_worker_count",
        "unexpected_worker": "database_unexpected_worker_count",
    }
    if field := count_fields.get(drift):
        payload[field] = 1
        return
    roles = payload["database_role_capabilities"]
    assert isinstance(roles, list)
    if drift == "runtime_login":
        roles[1]["can_login"] = True
        return
    rogue = dict(roles[1])
    rogue.update(
        {
            "name": "unregistered_writer",
            "oid": 12,
            "disposition": "inert_unregistered",
            "can_table_write": True,
        }
    )
    roles.append(rogue)
    payload["database_role_capability_count"] = 3


@pytest.mark.parametrize(
    "drift",
    [
        "prepared_transaction",
        "prepared_capability",
        "logical_subscription",
        "logical_apply_worker",
        "unexpected_worker",
        "runtime_login",
        "unregistered_writer",
    ],
)
def test_windows_writer_capability_drift_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    lifecycle = tmp_path / drift / "c07-lifecycle"
    lifecycle.mkdir(parents=True)
    path = lifecycle / f"operation-{_CEREMONY_ID}-freeze-proof.json"
    release_identity, encoded_envelope = _windows_freeze_envelope()
    envelope = json.loads(encoded_envelope)
    payload = json.loads(envelope["payload_json"])
    _apply_writer_capability_drift(payload, drift)
    payload_json = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    envelope["payload_json"] = payload_json
    envelope["payload_sha256"] = hashlib.sha256(
        payload_json.encode("utf-8")
    ).hexdigest().upper()
    write_protected_file_exclusive(
        path,
        c07._canonical_json(envelope),  # noqa: SLF001
    )
    monkeypatch.setattr(
        host_freeze_evidence,
        "hold_system_authority_file_for_read",
        hold_protected_file_for_read,
    )
    process_times = {4242: (10, 20), 4243: (30, 40)}
    monkeypatch.setattr(
        host_freeze_evidence,
        "windows_process_start_filetime",
        process_times.__getitem__,
    )

    with pytest.raises(
        c07.C07CeremonyError,
        match="durable writer fence",
    ):
        c07.read_host_freeze_evidence(
            path,
            expected_release_identity=release_identity,
            expected_parent_pid=4242,
        )


def test_noncanonical_or_extra_proof_fields_are_rejected(tmp_path: Path) -> None:
    extra = tmp_path / "extra.json"
    _write_proof(extra, _proof_payload(untrusted=True))
    with pytest.raises(c07.C07CeremonyError, match="schema or canonical"):
        c07.read_host_freeze_evidence(
            extra,
            expected_release_identity=_RELEASE_IDENTITY,
            expected_parent_pid=4242,
            allow_isolated_test=True,
        )

    noncanonical = tmp_path / "noncanonical.json"
    write_protected_file_exclusive(
        noncanonical,
        c07._canonical_json(_proof_payload()).replace(",", ", "),  # noqa: SLF001
    )
    with pytest.raises(c07.C07CeremonyError, match="schema or canonical"):
        c07.read_host_freeze_evidence(
            noncanonical,
            expected_release_identity=_RELEASE_IDENTITY,
            expected_parent_pid=4242,
            allow_isolated_test=True,
        )


def _future_lineage_config(tmp_path: Path) -> tuple[Config, str]:
    migration_root = tmp_path / "migrations"
    versions = migration_root / "versions"
    versions.mkdir(parents=True)
    future_revision = "20260801_0001"
    for file_name, revision, down_revision in (
        ("source.py", c07.C07_SOURCE_REVISION, None),
        ("c07.py", c07.C07_TARGET_REVISION, c07.C07_SOURCE_REVISION),
        ("future.py", future_revision, c07.C07_TARGET_REVISION),
    ):
        (versions / file_name).write_text(
            f"revision = {revision!r}\n"
            f"down_revision = {down_revision!r}\n"
            "branch_labels = None\n"
            "depends_on = None\n",
            encoding="utf-8",
        )
    config = Config()
    config.set_main_option("script_location", str(migration_root))
    return config, future_revision


@pytest.mark.parametrize(
    ("current_kind", "target_kind", "expected"),
    [
        ("before", "c07", True),
        ("before", "after", True),
        ("c07", "c07", False),
        ("c07", "after", False),
        ("after", "c07", False),
        ("after", "after", False),
    ],
)
def test_c07_gate_uses_revision_ancestry_across_future_heads(
    tmp_path: Path,
    current_kind: str,
    target_kind: str,
    expected: bool,
) -> None:
    config, future_revision = _future_lineage_config(tmp_path)
    revisions = {
        "before": c07.C07_SOURCE_REVISION,
        "c07": c07.C07_TARGET_REVISION,
        "after": future_revision,
    }
    assert c07.c07_managed_upgrade_required(
        current_revision=revisions[current_kind],
        target_revision=revisions[target_kind],
        alembic_config=config,
    ) is expected


def test_c07_gate_does_not_classify_fresh_install_as_managed(
    tmp_path: Path,
) -> None:
    config, future_revision = _future_lineage_config(tmp_path)
    assert not c07.c07_managed_upgrade_required(
        current_revision=None,
        target_revision=future_revision,
        alembic_config=config,
    )

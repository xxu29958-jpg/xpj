from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import layout
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.mutex import ThreadMutex
from ticketbox_lifecycle.schemas import (
    INSTALLATION_SCHEMA,
    OPERATION_SCHEMA,
    ActiveOperation,
    InstallationBinding,
)


class RecordingSecurity:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, str]] = []
        self.reject_reads = False

    def verify_machine_json(self, path: Path, reader_service: str) -> None:
        self.calls.append(("verify", path, reader_service))
        if self.reject_reads:
            raise LifecycleViolation("machine_state_untrusted", "machine JSON has no trusted owner")

    def verify_binding_json(self, path: Path, reader_service: str) -> None:
        self.calls.append(("verify-binding", path, reader_service))
        if self.reject_reads:
            raise LifecycleViolation("machine_state_untrusted", "machine JSON has no trusted owner")

    def protect_machine_json(self, path: Path, reader_service: str) -> None:
        self.calls.append(("protect", path, reader_service))

    def grant_backend_binding_read(self, path: Path, reader_service: str) -> None:
        self.calls.append(("grant-binding", path, reader_service))


def _stores(tmp_path: Path, security: RecordingSecurity) -> FilesystemStores:
    return FilesystemStores(
        tmp_path / "machine",
        "TicketboxBackend",
        SimpleNamespace(security=security),
        ThreadMutex(),
    )


def _active() -> ActiveOperation:
    return ActiveOperation(
        schema=OPERATION_SCHEMA,
        operation_id="11111111-1111-4111-8111-111111111111",
        kind="install",
        request_hash="a" * 64,
        target_release_id="1.2.0",
        data_root=r"C:\ProgramData\Ticketbox\data",
        release_manifest_sha256="b" * 64,
        backend_port=8000,
        phase="prepared",
        no_return_point=False,
        completed_step=None,
        install_id="22222222-2222-4222-8222-222222222222",
        dataset_id="33333333-3333-4333-8333-333333333333",
        schema_revision="20260821_0001",
        health_attestation_key="a" * 64,
    )


def _binding() -> InstallationBinding:
    return InstallationBinding(
        schema=INSTALLATION_SCHEMA,
        install_id="22222222-2222-4222-8222-222222222222",
        dataset_id="33333333-3333-4333-8333-333333333333",
        expected_restore_epoch=0,
        data_root=r"C:\ProgramData\Ticketbox\data",
        active_release_id="1.2.0",
        previous_release_id=None,
        release_manifest_sha256="b" * 64,
        postgres_major=17,
        pg_service_name="TicketboxPg",
        backend_service_name="TicketboxBackend",
        pg_port=5432,
        backend_port=8000,
        health_attestation_key="a" * 64,
    )


@pytest.mark.parametrize("name,payload,reader", [
    ("operations/active.json", asdict(_active()), "active"),
    ("installation.json", asdict(_binding()), "binding"),
])
def test_machine_json_is_verified_before_content_is_parsed(
    tmp_path: Path,
    name: str,
    payload: dict[str, object],
    reader: str,
) -> None:
    security = RecordingSecurity()
    stores = _stores(tmp_path, security)
    path = tmp_path / "machine" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    security.reject_reads = True

    with pytest.raises(LifecycleViolation, match="trusted owner"):
        stores.read_active() if reader == "active" else stores.read()

    expected_call = "verify" if reader == "active" else "verify-binding"
    assert security.calls == [(expected_call, path, "TicketboxBackend")]


def test_active_publication_protects_and_verifies_exact_file(tmp_path: Path) -> None:
    security = RecordingSecurity()
    stores = _stores(tmp_path, security)

    stores.publish_active(_active())

    path = tmp_path / "machine" / "operations" / "active.json"
    temp_path = security.calls[0][1]
    assert temp_path.parent == path.parent
    assert temp_path.name == layout.ACTIVE_OPERATION_TEMP_NAME
    assert security.calls == [
        ("protect", temp_path, "TicketboxBackend"),
        ("verify", temp_path, "TicketboxBackend"),
        ("verify", path, "TicketboxBackend"),
    ]


def test_active_reader_rejects_an_unknown_completed_step(tmp_path: Path) -> None:
    stores = _stores(tmp_path, RecordingSecurity())
    payload = asdict(_active())
    payload["completed_step"] = "foreign_step"
    path = tmp_path / "machine" / "operations" / "active.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LifecycleError, match="completed_step is invalid"):
        stores.read_active()


@pytest.mark.parametrize("reader", ["active", "binding"])
def test_machine_authority_readers_reject_an_extra_field(tmp_path: Path, reader: str) -> None:
    stores = _stores(tmp_path, RecordingSecurity())
    payload = asdict(_active() if reader == "active" else _binding())
    payload["legacy_fallback"] = True
    relative = "operations/active.json" if reader == "active" else "installation.json"
    path = tmp_path / "machine" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LifecycleError, match="fields are not closed"):
        stores.read_active() if reader == "active" else stores.read()


def test_committed_history_is_protected_and_verified_before_replay(tmp_path: Path) -> None:
    security = RecordingSecurity()
    stores = _stores(tmp_path, security)
    committed = replace(_active(), phase="committed", no_return_point=True)
    stores.publish_active(committed)
    security.calls.clear()

    stores.archive_committed(committed)

    history = tmp_path / "machine" / "operations" / "history" / f"{committed.operation_id}.json"
    temp_path = security.calls[0][1]
    assert security.calls == [
        ("protect", temp_path, "TicketboxBackend"),
        ("verify", temp_path, "TicketboxBackend"),
        ("verify", history, "TicketboxBackend"),
    ]
    security.calls.clear()
    assert stores.read_committed(committed.operation_id) == committed
    assert security.calls == [
        ("verify", history, "TicketboxBackend"),
        ("verify", history, "TicketboxBackend"),
    ]


def test_committed_history_rejects_an_unsafe_operation_key(tmp_path: Path) -> None:
    stores = _stores(tmp_path, RecordingSecurity())

    with pytest.raises(LifecycleViolation, match="safe history key"):
        stores.read_committed("../foreign")


def test_binding_publication_sets_exact_readers_before_replace_and_reverifies(tmp_path: Path) -> None:
    security = RecordingSecurity()
    stores = _stores(tmp_path, security)

    stores.publish(_binding())

    path = tmp_path / "machine" / "installation.json"
    temp_path = security.calls[0][1]
    assert temp_path.parent == path.parent
    assert temp_path.name.startswith("installation.json") and temp_path.name.endswith(".tmp")
    assert security.calls == [
        ("grant-binding", temp_path, "TicketboxBackend"),
        ("verify-binding", temp_path, "TicketboxBackend"),
        ("verify-binding", path, "TicketboxBackend"),
    ]

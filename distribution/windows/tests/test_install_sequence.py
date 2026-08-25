from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fakes import MemoryStores, RecordingAdapterBundle
from ticketbox_lifecycle import cli
from ticketbox_lifecycle.domain.install import (
    hash_install_identity,
    hash_request_payload,
    inspect_machine,
    install_or_resume,
)
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.schemas import APPLY_SEQUENCE, REQUEST_SCHEMA, InstallRequest


def _request(tmp_path: Path, operation_id: str = "11111111-1111-4111-8111-111111111111") -> InstallRequest:
    app_dir = tmp_path / "app"
    release_id = "1.2.0+deadbeef"
    manifest = app_dir / "releases" / release_id / "release-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    body = b'{"max_schema_revision":"20260821_0001"}\n'
    manifest.write_bytes(body)
    payload = {
        "schema": REQUEST_SCHEMA,
        "operation_id": operation_id,
        "target_release_id": release_id,
        "app_dir": str(app_dir),
        "data_root": str(tmp_path / "programdata" / "data"),
        "program_data_root": str(tmp_path / "programdata"),
        "pg_service_name": "TicketboxPg",
        "backend_service_name": "TicketboxBackend",
        "pg_port": 5432,
        "backend_port": 8000,
        "postgres_major": 17,
        "release_manifest_sha256": hashlib.sha256(body).hexdigest(),
    }
    return InstallRequest(
        schema=REQUEST_SCHEMA,
        command="install",
        operation_id=operation_id,
        request_hash=hash_request_payload(payload),
        target_release_id=str(payload["target_release_id"]),
        app_dir=str(payload["app_dir"]),
        data_root=str(payload["data_root"]),
        program_data_root=str(payload["program_data_root"]),
        pg_service_name=str(payload["pg_service_name"]),
        backend_service_name=str(payload["backend_service_name"]),
        pg_port=int(payload["pg_port"]),
        backend_port=int(payload["backend_port"]),
        postgres_major=int(payload["postgres_major"]),
        release_manifest_sha256=str(payload["release_manifest_sha256"]),
    )


def test_fresh_install_publishes_binding_only_after_health(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    seen_active_before_apply = {"value": False}
    seen_unpublished_through_health = {"value": False}

    original_files_apply = adapters.files.apply
    original_health_verify = adapters.dataset.verify

    def wrapped_files_apply(req: InstallRequest, step: str) -> str:
        assert stores.read_active() is not None
        assert stores.read_active().phase == "prepared"
        assert stores.read() is None
        seen_active_before_apply["value"] = True
        return original_files_apply(req, step)

    def wrapped_health_verify(req: InstallRequest, step: str) -> None:
        assert stores.read() is None
        seen_unpublished_through_health["value"] = True
        original_health_verify(req, step)

    adapters.files.apply = wrapped_files_apply  # type: ignore[method-assign]
    adapters.dataset.verify = wrapped_health_verify  # type: ignore[method-assign]
    result = install_or_resume(stores.as_lifecycle_stores(), request)
    assert result.ok
    assert result.phase == "committed"
    assert result.pairing_code == "12345678"
    assert result.pairing_expires_at == "2026-08-25T12:00:00Z"
    assert seen_active_before_apply["value"] is True
    assert stores.operation_store_prepared is True
    assert seen_unpublished_through_health["value"] is True
    assert stores.read() is not None
    assert stores.read_active() is not None
    assert stores.read_active().phase == "committed"
    assert stores.history == []
    assert adapters.apply_order() == list(APPLY_SEQUENCE)
    assert stores.binding_publish_count == 1
    assert stores.fresh_inputs_check_count == 1
    binding = stores.read()
    assert binding is not None
    assert binding.install_id
    assert binding.dataset_id
    assert binding.release_manifest_sha256 == request.release_manifest_sha256
    assert binding.release_manifest_sha256 != "pending"


def test_health_failure_keeps_binding_unpublished(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    adapters.dataset.fail_on = "health"
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    result = install_or_resume(stores.as_lifecycle_stores(), request)
    assert result.ok is False
    assert result.installation_published is False
    assert stores.read() is None
    assert stores.read_active() is not None
    assert stores.read_active().phase == "failed_recoverable"
    assert stores.history == []


def test_resume_after_health_failure_publishes_binding_once_after_success(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    adapters.dataset.fail_on = "health"
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    first = install_or_resume(stores.as_lifecycle_stores(), request)
    assert first.ok is False
    assert stores.read() is None
    adapters.dataset.fail_on = None
    resume = InstallRequest(**{**request.__dict__, "command": "resume"})
    second = install_or_resume(stores.as_lifecycle_stores(), resume)
    assert second.ok
    assert second.phase == "committed"
    assert stores.binding_publish_count == 1
    assert stores.read() is not None
    assert stores.read_active() is not None
    assert stores.read_active().phase == "committed"
    assert stores.fresh_inputs_check_count == 1


def test_committed_result_is_durable_before_active_operation_is_archived(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    result = install_or_resume(stores.as_lifecycle_stores(), request)
    result_path = tmp_path / "result.json"

    assert cli._deliver_install_result(result_path, result, stores.as_lifecycle_stores()) == 0
    delivered = json.loads(result_path.read_text(encoding="utf-8"))
    assert delivered["ok"] is True
    assert delivered["pairing_code"] == "12345678"
    assert stores.read_active() is None
    assert [operation.phase for operation in stores.history] == ["committed"]


def test_archived_commit_replays_pairing_after_setup_crashes_before_consuming_result(
    tmp_path: Path,
) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path, operation_id="fresh-" + "a" * 64)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    first = install_or_resume(stores.as_lifecycle_stores(), request)
    first_result = tmp_path / "first-setup" / "result.json"

    assert cli._deliver_install_result(first_result, first, stores.as_lifecycle_stores()) == 0
    assert stores.read_active() is None
    assert stores.read_committed(request.operation_id) is not None

    replay_request = InstallRequest(**{**request.__dict__, "command": "resume"})
    replay = install_or_resume(stores.as_lifecycle_stores(), replay_request)
    second_result = tmp_path / "second-setup" / "result.json"

    assert replay.ok is True
    assert replay.operation_id == request.operation_id
    assert replay.pairing_code == first.pairing_code
    assert cli._deliver_install_result(second_result, replay, stores.as_lifecycle_stores()) == 0
    assert json.loads(second_result.read_text(encoding="utf-8"))["pairing_code"] == "12345678"


def test_archived_result_replay_does_not_take_over_another_active_operation(
    tmp_path: Path,
) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path, operation_id="fresh-" + "a" * 64)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    first = install_or_resume(stores.as_lifecycle_stores(), request)
    assert cli._deliver_install_result(
        tmp_path / "first.json",
        first,
        stores.as_lifecycle_stores(),
    ) == 0
    replay_request = InstallRequest(**{**request.__dict__, "command": "resume"})
    replay = install_or_resume(stores.as_lifecycle_stores(), replay_request)
    committed = stores.read_committed(request.operation_id)
    assert committed is not None
    foreign = replace(committed, operation_id="foreign-operation")
    stores.prepare(request)
    stores.publish_active(foreign)

    assert cli._deliver_install_result(
        tmp_path / "replay.json",
        replay,
        stores.as_lifecycle_stores(),
    ) == 2
    assert stores.read_active() == foreign


def test_result_write_failure_keeps_committed_operation_for_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    first = install_or_resume(stores.as_lifecycle_stores(), request)

    def fail_result_write(path: Path, result: object) -> None:
        del path, result
        raise OSError("injected result write failure")

    monkeypatch.setattr(cli, "_write_result", fail_result_write)
    with pytest.raises(OSError, match="result write failure"):
        cli._deliver_install_result(tmp_path / "result.json", first, stores.as_lifecycle_stores())

    assert stores.read_active() is not None
    assert stores.read_active().phase == "committed"
    assert stores.history == []
    resume = InstallRequest(**{**request.__dict__, "command": "resume"})
    replay = install_or_resume(stores.as_lifecycle_stores(), resume)
    assert replay.ok is True
    assert replay.pairing_code == first.pairing_code
    assert replay.pairing_expires_at == first.pairing_expires_at


def test_fresh_install_refuses_unbound_mutable_state_before_publishing_active(
    tmp_path: Path,
) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    stores.reject_fresh_inputs = True

    try:
        install_or_resume(stores.as_lifecycle_stores(), request)
        raise AssertionError("fresh install must reject preexisting mutable state")
    except LifecycleViolation as exc:
        assert exc.code == "preexisting_mutable_state"

    assert stores.read_active() is None
    assert stores.fresh_inputs_check_count == 1


def test_second_install_refuses_new_identity(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    assert install_or_resume(stores.as_lifecycle_stores(), request).ok
    try:
        install_or_resume(stores.as_lifecycle_stores(), request)
        raise AssertionError("second install must fail")
    except LifecycleViolation as exc:
        assert exc.code == "already_installed"


def test_resume_replays_from_postcondition_not_from_memory(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    adapters.postgres.fail_on = "postgres_initdb"
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    first = install_or_resume(stores.as_lifecycle_stores(), request)
    assert first.ok is False
    adapters.postgres.fail_on = None
    resume = InstallRequest(**{**request.__dict__, "command": "resume"})
    second = install_or_resume(stores.as_lifecycle_stores(), resume)
    assert second.ok
    assert adapters.files.apply_calls == 1
    assert adapters.security.apply_calls == 1
    assert adapters.postgres.applied == ["postgres_initdb", "start_postgres", "roles_database"]
    assert adapters.postgres.apply_calls == 4


def test_resume_rejects_different_operation_or_data_root(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    adapters.postgres.fail_on = "postgres_initdb"
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    assert install_or_resume(stores.as_lifecycle_stores(), request).ok is False
    other_op = InstallRequest(**{**request.__dict__, "operation_id": "22222222-2222-4222-8222-222222222222"})
    try:
        install_or_resume(stores.as_lifecycle_stores(), other_op)
        raise AssertionError("different operation_id must not take over")
    except LifecycleViolation as exc:
        assert exc.code == "operation_conflict"
    other_root = InstallRequest(**{**request.__dict__, "data_root": str(tmp_path / "other-data")})
    try:
        install_or_resume(stores.as_lifecycle_stores(), other_root)
        raise AssertionError("different data_root must not resume")
    except LifecycleViolation as exc:
        assert exc.code == "request_mismatch"


def test_install_identity_hash_ignores_operation_id(tmp_path: Path) -> None:
    first = _request(tmp_path, "11111111-1111-4111-8111-111111111111")
    second = _request(tmp_path, "22222222-2222-4222-8222-222222222222")
    assert hash_install_identity(first) == hash_install_identity(second)
    moved = InstallRequest(**{**first.__dict__, "data_root": str(tmp_path / "moved")})
    assert hash_install_identity(first) != hash_install_identity(moved)


def test_release_hash_mismatch_refuses_install(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path)
    tampered = InstallRequest(**{**request.__dict__, "release_manifest_sha256": "c" * 64})
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    try:
        install_or_resume(stores.as_lifecycle_stores(), tampered)
        raise AssertionError("wrong manifest hash must not install")
    except LifecycleViolation as exc:
        assert exc.code == "release_hash_mismatch"
    pending = InstallRequest(**{**request.__dict__, "release_manifest_sha256": "pending"})
    try:
        install_or_resume(stores.as_lifecycle_stores(), pending)
        raise AssertionError("pending manifest hash must not install")
    except LifecycleViolation as exc:
        assert exc.code == "release_hash_mismatch"


def test_inspect_does_not_mutate(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    inspect = inspect_machine(stores.as_lifecycle_stores(), request)
    assert inspect.ok
    assert adapters.apply_order() == []
    assert stores.read() is None
    assert stores.read_active() is None


def test_request_hash_is_canonical() -> None:
    payload = {"b": 1, "a": 2}
    assert hash_request_payload(payload) == hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

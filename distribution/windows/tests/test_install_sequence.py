from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ticketbox_lifecycle.domain.install import hash_request_payload, inspect_machine, install_or_resume
from ticketbox_lifecycle.errors import LifecycleViolation
from ticketbox_lifecycle.schemas import APPLY_SEQUENCE, REQUEST_SCHEMA, InstallRequest

from fakes import MemoryStores, RecordingAdapterBundle


def _request(tmp_path: Path, operation_id: str = "11111111-1111-4111-8111-111111111111") -> InstallRequest:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    payload = {
        "schema": REQUEST_SCHEMA,
        "operation_id": operation_id,
        "target_release_id": "1.2.0+deadbeef",
        "app_dir": str(app_dir),
        "data_root": str(tmp_path / "data"),
        "program_data_root": str(tmp_path / "programdata"),
        "pg_service_name": "TicketboxPg",
        "backend_service_name": "TicketboxBackend",
        "pg_port": 5432,
        "backend_port": 8000,
        "postgres_major": 17,
        "release_manifest_sha256": "a" * 64,
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


def test_fresh_install_publishes_active_before_first_adapter_and_binding_last(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    request = _request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    seen_active_before_apply = {"value": False}

    original_apply = adapters.files.apply

    def wrapped_apply(req: InstallRequest, step: str) -> str:
        assert stores.read_active() is not None
        assert stores.read_active().phase == "prepared"
        assert stores.read() is None
        seen_active_before_apply["value"] = True
        return original_apply(req, step)

    adapters.files.apply = wrapped_apply  # type: ignore[method-assign]
    result = install_or_resume(stores.as_lifecycle_stores(), request)
    assert result.ok
    assert result.phase == "committed"
    assert seen_active_before_apply["value"] is True
    assert stores.read() is not None
    assert stores.read_active() is None
    assert stores.history[0].phase == "committed"
    assert adapters.apply_order() == list(APPLY_SEQUENCE)
    assert stores.binding_publish_count == 1
    binding = stores.read()
    assert binding is not None
    assert binding.install_id
    assert binding.dataset_id


def test_health_failure_does_not_publish_installation(tmp_path: Path) -> None:
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

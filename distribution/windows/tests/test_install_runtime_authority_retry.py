from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import pytest
from backend.packaging.launch import _closed_authorities
from fakes import MemoryStores, RecordingAdapterBundle, make_install_request
from ticketbox_lifecycle.domain.install import install_or_resume
from ticketbox_lifecycle.schemas import ActiveOperation, InstallRequest


@pytest.mark.parametrize("failure_boundary", ["binding", "commit"])
def test_post_health_publication_failure_resumes_with_runtime_closed_authority(
    tmp_path: Path,
    failure_boundary: str,
) -> None:
    adapters = RecordingAdapterBundle()
    request = make_install_request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    original_start = adapters.scm.apply
    original_publish_binding = stores.publish
    original_publish_active = stores.publish_active
    fail_once = {failure_boundary: True}
    backend_starts: list[tuple[str, str | None]] = []

    def start_backend(bound: InstallRequest, step: str) -> str:
        if step == "start_services":
            binding = stores.read()
            active = stores.read_active()
            assert active is not None
            _closed_authorities(
                None if binding is None else asdict(binding),
                asdict(active),
            )
            backend_starts.append((active.phase, active.completed_step))
        return original_start(bound, step)

    def publish_binding(binding) -> None:
        if fail_once.get("binding"):
            fail_once["binding"] = False
            raise OSError("injected binding publication failure")
        original_publish_binding(binding)

    def publish_active(operation: ActiveOperation) -> None:
        if operation.phase == "committed" and fail_once.get("commit"):
            fail_once["commit"] = False
            raise OSError("injected committed publication failure")
        original_publish_active(operation)

    adapters.scm.apply = start_backend  # type: ignore[method-assign]
    stores.publish = publish_binding  # type: ignore[method-assign]
    stores.publish_active = publish_active  # type: ignore[method-assign]

    first = install_or_resume(stores.as_lifecycle_stores(), request)
    assert first.ok is False
    initdb_apply_calls = adapters.postgres.applied.count("postgres_initdb")

    resumed = install_or_resume(
        stores.as_lifecycle_stores(),
        replace(request, command="resume"),
    )

    assert resumed.ok is True
    assert resumed.phase == "committed"
    assert adapters.postgres.applied.count("postgres_initdb") == initdb_apply_calls
    assert backend_starts == [
        ("data_ready", "owner_claim"),
        ("data_ready", "owner_claim"),
    ]

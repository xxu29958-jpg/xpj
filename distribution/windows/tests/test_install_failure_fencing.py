from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fakes import MemoryStores, RecordingAdapterBundle, make_install_request
from ticketbox_lifecycle.domain.binding import binding_from_request
from ticketbox_lifecycle.domain.install import install_or_resume
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.schemas import ActiveOperation, InstallRequest


def test_health_failure_is_fenced_before_failed_authority_is_published(
    tmp_path: Path,
) -> None:
    adapters = RecordingAdapterBundle()
    adapters.dataset.fail_on = "health"
    request = make_install_request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    order: list[str] = []
    original_fence = adapters.scm.fence_backend
    original_publish_active = stores.publish_active

    def fence_backend(bound: InstallRequest) -> None:
        order.append("fence")
        original_fence(bound)

    def publish_active(operation: ActiveOperation) -> None:
        if operation.phase == "failed_recoverable":
            order.append("failed")
        original_publish_active(operation)

    adapters.scm.fence_backend = fence_backend  # type: ignore[method-assign]
    stores.publish_active = publish_active  # type: ignore[method-assign]

    result = install_or_resume(stores.as_lifecycle_stores(), request)

    assert result.ok is False
    assert order == ["fence", "failed"]


def test_backend_fence_failure_preserves_primary_and_cleanup_truth(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    adapters.dataset.fail_on = "health"
    adapters.scm.fail_fence = True
    request = make_install_request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)

    result = install_or_resume(stores.as_lifecycle_stores(), request)

    assert result.ok is False
    assert result.code == "injected_failure"
    assert "forced failure at health" in result.message
    assert "injected_fence_failure" in result.message
    assert "forced backend fence failure" in result.message
    assert stores.read_active() is not None
    assert stores.read_active().phase == "failed_recoverable"


def test_resume_prepare_failure_is_owned_and_fences_existing_runtime(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    adapters.dataset.fail_on = "health"
    request = make_install_request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    assert install_or_resume(stores.as_lifecycle_stores(), request).ok is False
    active = stores.read_active()
    assert active is not None
    stores.publish_active(replace(active, phase="release_activated", no_return_point=True))
    adapters.dataset.fail_on = None
    adapters.scm.fence_calls = 0
    adapters.scm.backend_fenced = False
    adapters.scm._done.add("start_services")

    def fail_prepare(_request: InstallRequest) -> None:
        raise OSError("forced prepare failure")

    stores.prepare = fail_prepare  # type: ignore[method-assign]
    resume = replace(request, command="resume")

    result = install_or_resume(stores.as_lifecycle_stores(), resume)

    assert result.ok is False
    assert result.code == "operation_io_failed"
    assert adapters.scm.fence_calls == 1
    assert adapters.scm.backend_fenced is True
    assert stores.read_active() is not None
    assert stores.read_active().phase == "failed_recoverable"


def test_failure_result_preserves_primary_when_cleanup_state_writes_also_fail(
    tmp_path: Path,
) -> None:
    adapters = RecordingAdapterBundle()
    adapters.dataset.fail_on = "health"
    adapters.scm.fail_fence = True
    request = make_install_request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    original_publish_active = stores.publish_active
    original_read_binding = stores.read
    binding_reads = 0

    def fail_failed_publication(operation: ActiveOperation) -> None:
        if operation.phase == "failed_recoverable":
            raise LifecycleError("active_publish_failed", "forced failed-state publication failure")
        original_publish_active(operation)

    def fail_binding_readback():
        nonlocal binding_reads
        binding_reads += 1
        if binding_reads > 1:
            raise OSError("forced binding readback failure")
        return original_read_binding()

    stores.publish_active = fail_failed_publication  # type: ignore[method-assign]
    stores.read = fail_binding_readback  # type: ignore[method-assign]

    result = install_or_resume(stores.as_lifecycle_stores(), request)

    assert result.ok is False
    assert result.code == "injected_failure"
    assert result.phase == "release_activated"
    assert "injected_fence_failure" in result.message
    assert "active_publish_failed" in result.message
    assert "operation_io_failed" in result.message
    assert stores.read_active() is not None
    assert stores.read_active().phase == "data_ready"


def test_resume_binding_read_failure_fences_existing_runtime(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    adapters.dataset.fail_on = "health"
    request = make_install_request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    assert install_or_resume(stores.as_lifecycle_stores(), request).ok is False
    active = stores.read_active()
    assert active is not None
    stores.publish_active(replace(active, phase="release_activated", no_return_point=True))
    adapters.scm.fence_calls = 0
    adapters.scm.backend_fenced = False
    adapters.scm._done.add("start_services")

    def fail_binding_read() -> None:
        raise OSError("forced binding read failure")

    stores.read = fail_binding_read  # type: ignore[method-assign]

    result = install_or_resume(stores.as_lifecycle_stores(), replace(request, command="resume"))

    assert result.ok is False
    assert result.code == "operation_io_failed"
    assert adapters.scm.fence_calls == 1
    assert adapters.scm.backend_fenced is True
    assert stores.read_active() is not None
    assert stores.read_active().phase == "failed_recoverable"


def test_resume_conflicting_binding_is_rejected_without_fencing(tmp_path: Path) -> None:
    adapters = RecordingAdapterBundle()
    adapters.dataset.fail_on = "health"
    request = make_install_request(tmp_path)
    stores = MemoryStores(adapters, request.app_dir, request.data_root)
    assert install_or_resume(stores.as_lifecycle_stores(), request).ok is False
    active = stores.read_active()
    assert active is not None
    bound = replace(request, install_id=active.install_id, dataset_id=active.dataset_id)
    stores.publish(
        replace(
            binding_from_request(bound),
            dataset_id="22222222-2222-4222-8222-222222222222",
        )
    )
    adapters.scm.fence_calls = 0

    with pytest.raises(LifecycleViolation) as raised:
        install_or_resume(stores.as_lifecycle_stores(), replace(request, command="resume"))

    assert raised.value.code == "already_installed"
    assert adapters.scm.fence_calls == 0

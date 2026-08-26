from __future__ import annotations

from pathlib import Path

from fakes import MemoryStores, RecordingAdapterBundle, make_install_request
from ticketbox_lifecycle.domain.install import install_or_resume
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

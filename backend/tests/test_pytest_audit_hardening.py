from __future__ import annotations

import importlib.util
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_packaging_tests
from scripts.pytest_execution_contract import pytest_execution_environment

pytestmark = pytest.mark.parallel_safe


def _load_module(relative_path: str, module_name: str) -> ModuleType:
    path = run_packaging_tests.BACKEND_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _ResourceItem:
    def __init__(self, nodeid: str, resource: str, marker_name: str) -> None:
        self.nodeid = nodeid
        self._marker_name = marker_name
        self._resource_marker = SimpleNamespace(args=(resource,), kwargs={})
        self._generated_markers: dict[str, list[SimpleNamespace]] = {}

    def iter_markers_with_node(
        self,
        name: str,
    ) -> tuple[tuple[_ResourceItem, SimpleNamespace], ...]:
        markers = []
        if name == self._marker_name:
            markers.append(self._resource_marker)
        markers.extend(self._generated_markers.get(name, ()))
        return tuple((self, marker) for marker in markers)

    def get_closest_marker(self, name: str) -> SimpleNamespace | None:
        markers = self._generated_markers.get(name, ())
        return None if not markers else markers[-1]

    def add_marker(self, marker: object) -> None:
        value = marker.mark
        self._generated_markers.setdefault(value.name, []).append(value)


@pytest.mark.parametrize("resource", ("hermetic", "windows_host"))
def test_packaging_collection_assigns_only_runtime_scheduler_groups(
    resource: str,
) -> None:
    module = _load_module(
        "packaging/tests/conftest.py",
        f"xpj_packaging_resource_probe_{resource}",
    )
    item = _ResourceItem(
        f"packaging/tests/test_{resource}.py::test_contract",
        resource,
        module.PACKAGING_RESOURCE_MARKER,
    )

    hook = module.pytest_collection_modifyitems([item])
    next(hook)
    with pytest.raises(StopIteration):
        next(hook)


def test_packaging_collection_rejects_a_late_rogue_xdist_group() -> None:
    module = _load_module(
        "packaging/tests/conftest.py",
        "xpj_packaging_late_group_probe",
    )
    nodeid = "packaging/tests/test_windows_host.py::test_contract"
    item = _ResourceItem(nodeid, "windows_host", module.PACKAGING_RESOURCE_MARKER)
    hook = module.pytest_collection_modifyitems([item])
    next(hook)
    item.add_marker(
        SimpleNamespace(
            mark=SimpleNamespace(
                name="xdist_group",
                args=("rogue-nested-group",),
                kwargs={},
            )
        )
    )
    with pytest.raises(pytest.UsageError, match="exactly one generated"):
        next(hook)


_WINDOWS_HOST_CUTOVER_NODEIDS = (
    "packaging/tests/test_backend_bootstrap_contract.py::"
    "test_maintenance_failure_writes_credential_free_durable_result",
    "packaging/tests/test_backend_bootstrap_contract.py::test_owner_handoff_takeover_requires_dead_previous_installer",
    "packaging/tests/test_backend_bootstrap_contract.py::test_bootstrap_request_bypasses_default_proxy",
    "packaging/tests/test_backend_bootstrap_contract.py::"
    "test_bootstrap_request_exception_revalidates_listener_and_stops_on_failure",
    "packaging/tests/test_build_provenance_contract.py::"
    "test_installer_publish_unit_validator_rejects_contract_mutations",
    "packaging/tests/test_build_provenance_contract.py::test_windows_build_lock_is_bound_to_current_requirement_inputs",
    "packaging/tests/test_installer_lifecycle_contract.py::"
    "test_delete_data_requires_completed_receipt_or_bound_retry_intent",
    "packaging/tests/test_installer_lifecycle_contract.py::"
    "test_external_lifecycle_lock_holder_keeps_authority_until_release",
    "packaging/tests/test_installer_lifecycle_contract.py::"
    "test_data_root_guard_authenticates_holder_and_cleans_ipc_after_owner_death",
    "packaging/tests/test_installer_lifecycle_contract.py::"
    "test_holder_entrypoint_independently_rejects_wrong_parent_and_non_authoritative_root",
    "packaging/tests/test_installer_lifecycle_contract.py::"
    "test_exact_deletion_defers_data_root_authority_marker_and_retries_only_empty_root",
    "packaging/tests/test_installer_lifecycle_contract.py::"
    "test_data_root_guard_lease_blocks_cross_process_root_and_ancestor_rename",
    "packaging/tests/test_installer_lifecycle_contract.py::"
    "test_windows_safety_helpers_execute_in_available_powershells",
    "packaging/tests/test_legacy_installer_security.py::"
    "test_bootstrap_http_exception_revalidates_listener_and_fails_closed",
    "packaging/tests/test_legacy_installer_security.py::"
    "test_bootstrap_requires_owned_listener_and_sends_utf8_json_bytes",
    "packaging/tests/test_service_lifecycle_contract.py::"
    "test_tcp_listener_query_handles_native_empty_and_close_in_powershell_5_and_7",
)
_POSTGRES_CLUSTER_CUTOVER_NODEIDS = (
    "packaging/tests/test_local_test_postgres_lifecycle.py::"
    "test_local_test_postgres_rejects_a_different_cluster_before_provisioning",
    "packaging/tests/test_local_test_postgres_lifecycle.py::"
    "test_legacy_trust_cluster_scram_migration_is_reentrant[after-password]",
    "packaging/tests/test_local_test_postgres_lifecycle.py::"
    "test_legacy_trust_cluster_scram_migration_is_reentrant[after-hba]",
)


def test_high_risk_packaging_cutover_tests_remain_serial() -> None:
    expected = _WINDOWS_HOST_CUTOVER_NODEIDS + _POSTGRES_CLUSTER_CUTOVER_NODEIDS
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *expected,
            "--collect-only",
            "-q",
            "--strict-markers",
            "-p",
            "no:cacheprovider",
            "-m",
            "xdist_group",
            "-o",
            "addopts=",
        ],
        cwd=run_packaging_tests.BACKEND_ROOT,
        env=pytest_execution_environment(
            remove_keys=(run_packaging_tests.STRICT_WINDOWS_RUNTIME_ENV,),
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    selected = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("packaging/tests/") and "::" in line
    }
    assert result.returncode == 0, result.stdout + result.stderr
    assert selected == set(expected)


class _RuntimeStack:
    def __init__(self, *, fail: bool = False) -> None:
        self.closed = False
        self._fail = fail

    def close(self) -> None:
        self.closed = True
        if self._fail:
            raise RuntimeError("runtime cleanup failed")


def test_backend_worker_completion_requires_runtime_cleanup_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module("tests/conftest.py", "xpj_backend_cleanup_probe")
    monkeypatch.setattr(module, "cleanup_runtime", lambda: None)
    runtime_stack = _RuntimeStack()
    worker = SimpleNamespace(
        workerinput={"workerid": "gw0"},
        workeroutput={},
        _xpj_postgres_runtime_stack=runtime_stack,
    )
    module.pytest_sessionfinish(SimpleNamespace(config=worker), pytest.ExitCode.OK)
    assert runtime_stack.closed
    assert worker.workeroutput[module._WORKER_RUNTIME_CLOSED_KEY] is True  # noqa: SLF001

    failing_worker = SimpleNamespace(
        workerinput={"workerid": "gw1"},
        workeroutput={},
        _xpj_postgres_runtime_stack=_RuntimeStack(fail=True),
    )
    with pytest.raises(RuntimeError, match="runtime cleanup failed"):
        module.pytest_sessionfinish(
            SimpleNamespace(config=failing_worker),
            pytest.ExitCode.OK,
        )
    assert module._WORKER_RUNTIME_CLOSED_KEY not in failing_worker.workeroutput  # noqa: SLF001

    def fail_filesystem_cleanup() -> None:
        raise RuntimeError("filesystem cleanup failed")

    monkeypatch.setattr(module, "cleanup_runtime", fail_filesystem_cleanup)
    cleanup_failure_stack = _RuntimeStack()
    cleanup_failure_worker = SimpleNamespace(
        workerinput={"workerid": "gw2"},
        workeroutput={},
        _xpj_postgres_runtime_stack=cleanup_failure_stack,
    )
    with pytest.raises(RuntimeError, match="filesystem cleanup failed"):
        module.pytest_sessionfinish(
            SimpleNamespace(config=cleanup_failure_worker),
            pytest.ExitCode.OK,
        )
    assert cleanup_failure_stack.closed
    assert module._WORKER_RUNTIME_CLOSED_KEY not in cleanup_failure_worker.workeroutput  # noqa: SLF001

    controller = SimpleNamespace()
    module._initialize_runner_state(controller)  # noqa: SLF001
    node = SimpleNamespace(
        config=controller,
        gateway=SimpleNamespace(id="gw0"),
        workeroutput={},
    )
    module.pytest_testnodedown(node, None)
    assert "cleanup" in controller._xpj_xdist_worker_errors["gw0"]

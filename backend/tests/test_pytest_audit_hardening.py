from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_packaging_tests
from scripts.packaging_pytest_contract import (
    PACKAGING_RESOURCE_MEMBERSHIP_MARKERS,
    packaging_resource_membership_marker,
)
from scripts.pytest_execution_contract import (
    pytest_execution_environment,
    pytest_nodeid_digest,
)

pytestmark = pytest.mark.parallel_safe


def _load_module(relative_path: str, module_name: str) -> ModuleType:
    path = run_packaging_tests.BACKEND_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _set_packaging_membership_proofs(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    nodeid: str,
    *,
    resource: str,
) -> None:
    parallel_nodeids = (nodeid,) if resource == "hermetic" else ()
    serial_nodeids = () if resource == "hermetic" else (nodeid,)
    proofs = (
        (module.PYTEST_EXPECTED_COUNT_ENV, module.PYTEST_EXPECTED_DIGEST_ENV, (nodeid,)),
        (
            module.PACKAGING_EXPECTED_PARALLEL_COUNT_ENV,
            module.PACKAGING_EXPECTED_PARALLEL_DIGEST_ENV,
            parallel_nodeids,
        ),
        (
            module.PACKAGING_EXPECTED_SERIAL_COUNT_ENV,
            module.PACKAGING_EXPECTED_SERIAL_DIGEST_ENV,
            serial_nodeids,
        ),
    )
    for count_env, digest_env, nodeids in proofs:
        monkeypatch.setenv(count_env, str(len(nodeids)))
        monkeypatch.setenv(digest_env, pytest_nodeid_digest(nodeids))


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
        if isinstance(marker, str):
            name = marker
            value = SimpleNamespace(args=(), kwargs={})
        else:
            value = marker.mark
            name = value.name
        self._generated_markers.setdefault(name, []).append(value)


@pytest.mark.parametrize("resource", ("hermetic", "windows_host"))
def test_packaging_collection_accepts_a_proven_empty_derived_lane(
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
) -> None:
    module = _load_module(
        "packaging/tests/conftest.py",
        "xpj_packaging_empty_lane_probe",
    )
    monkeypatch.setenv(module._STRICT_RUNTIME_ENV, "1")  # noqa: SLF001
    nodeid = f"packaging/tests/test_{resource}.py::test_contract"
    _set_packaging_membership_proofs(
        monkeypatch,
        module,
        nodeid,
        resource=resource,
    )
    item = _ResourceItem(nodeid, resource, module.PACKAGING_RESOURCE_MARKER)

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
    "packaging/tests/test_backend_bootstrap_contract.py::"
    "test_owner_handoff_takeover_requires_dead_previous_installer",
    "packaging/tests/test_backend_bootstrap_contract.py::"
    "test_bootstrap_request_bypasses_default_proxy",
    "packaging/tests/test_backend_bootstrap_contract.py::"
    "test_bootstrap_request_exception_revalidates_listener_and_stops_on_failure",
    "packaging/tests/test_build_provenance_contract.py::"
    "test_installer_publish_unit_validator_rejects_contract_mutations",
    "packaging/tests/test_build_provenance_contract.py::"
    "test_windows_build_lock_is_bound_to_current_requirement_inputs",
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


@pytest.mark.parametrize(
    ("resource", "expected"),
    (
        ("windows_host", _WINDOWS_HOST_CUTOVER_NODEIDS),
        ("postgres_cluster", _POSTGRES_CLUSTER_CUTOVER_NODEIDS),
    ),
)
def test_high_risk_packaging_cutover_resources_are_exact(
    resource: str,
    expected: tuple[str, ...],
) -> None:
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
            packaging_resource_membership_marker(resource),
            "-o",
            "addopts=",
        ],
        cwd=run_packaging_tests.BACKEND_ROOT,
        env=pytest_execution_environment(
            remove_keys=(run_packaging_tests.STRICT_WINDOWS_RUNTIME_ENV,)
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

    controller = SimpleNamespace()
    module._initialize_runner_state(controller)  # noqa: SLF001
    node = SimpleNamespace(
        config=controller,
        gateway=SimpleNamespace(id="gw0"),
        workeroutput={},
    )
    module.pytest_testnodedown(node, None)
    assert "cleanup" in controller._xpj_xdist_worker_errors["gw0"]


def test_pre_cutover_base_has_no_invented_packaging_partitions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audit = _load_module(
        "scripts/_audit_pr_delta_metrics.py",
        "xpj_pre_cutover_audit_probe",
    )
    backend_root = tmp_path / "legacy-backend"
    backend_root.mkdir()
    packaging_nodeid = "packaging/tests/test_old.py::test_old"

    def collect(
        _target: str,
        *,
        mark_expression: str | None = None,
        **_kwargs: object,
    ) -> tuple[int, tuple[str, ...]]:
        nodeids = (packaging_nodeid,) if mark_expression is None else ()
        return len(nodeids), nodeids

    monkeypatch.setattr(audit, "_collect_pytest_tests", collect)
    contract = audit._load_base_marker_contract(backend_root)
    assert contract == audit._LEGACY_BASE_MARKER_CONTRACT  # noqa: SLF001
    assert audit._collect_packaging_memberships(backend_root, contract) == {
        "packaging_all": (packaging_nodeid,),
        "packaging_parallel": (),
        "packaging_serial": (),
        **dict.fromkeys(PACKAGING_RESOURCE_MEMBERSHIP_MARKERS, ()),
    }


def _write_base_marker_contract(backend_root: Path) -> None:
    scripts = backend_root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "pytest_marker_contract.py").write_text(
        "\n".join(
            (
                "PYTEST_MARKER_CONTRACT_SCHEMA_VERSION = 2",
                'BACKEND_PARALLEL_SAFE_MARKER = "base_parallel_safe"',
                'BACKEND_REAL_DB_MARKER = "base_real_db"',
                'BACKEND_STATEFUL_MARKER = "base_stateful"',
                'BACKEND_CLUSTER_MARKER = "base_cluster"',
                'PACKAGING_PARALLEL_MARKER = "base_packaging_parallel"',
                'PACKAGING_SERIAL_MARKER = "base_packaging_serial"',
                "PACKAGING_RESOURCE_MEMBERSHIP_MARKERS = (",
                "    'packaging_resource_hermetic',",
                "    'packaging_resource_inno_toolchain',",
                "    'packaging_resource_postgres_cluster',",
                "    'packaging_resource_windows_fs',",
                "    'packaging_resource_windows_host',",
                ")",
            )
        ),
        encoding="utf-8",
    )


def test_base_marker_contract_drives_snapshot_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audit = _load_module(
        "scripts/_audit_pr_delta_metrics.py",
        "xpj_base_marker_audit_probe",
    )
    backend_root = tmp_path / "base-backend"
    _write_base_marker_contract(backend_root)
    packaging_nodeid = "packaging/tests/test_old.py::test_old"
    observed: list[str] = []

    def collect(
        target: str,
        *,
        mark_expression: str | None = None,
        **_kwargs: object,
    ) -> tuple[int, tuple[str, ...]]:
        if mark_expression is not None:
            observed.append(mark_expression)
        if target == "tests":
            nodeids = ("tests/test_old.py::test_old",) if mark_expression is None else ()
        else:
            nodeids = (
                (packaging_nodeid,)
                if mark_expression in (
                    None,
                    "base_packaging_serial",
                    "packaging_resource_inno_toolchain",
                )
                else ()
            )
        return len(nodeids), nodeids

    monkeypatch.setattr(audit, "_collect_pytest_tests", collect)
    contract = audit._load_base_marker_contract(backend_root)
    memberships = audit._collect_pytest_memberships(backend_root, contract)
    assert memberships["packaging_serial"] == (packaging_nodeid,)
    assert memberships["packaging_resource_inno_toolchain"] == (packaging_nodeid,)
    assert set(observed) == {
        "not base_stateful",
        "base_parallel_safe",
        "base_real_db",
        "base_stateful",
        "base_cluster",
        "base_packaging_parallel",
        "base_packaging_serial",
        *PACKAGING_RESOURCE_MEMBERSHIP_MARKERS,
    }


def test_pr_delta_main_propagates_membership_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _load_module(
        "scripts/_audit_pr_delta_metrics.py",
        "xpj_pr_delta_exit_probe",
    )
    memberships = {
        "backend_all": (),
        "backend_parallel": (),
        "parallel_safe": (),
        "real_db": (),
        "stateful_serial": (),
        "cluster_serial": (),
        "packaging_all": (),
        "packaging_parallel": (),
        "packaging_serial": (),
        **dict.fromkeys(PACKAGING_RESOURCE_MEMBERSHIP_MARKERS, ()),
    }
    monkeypatch.setattr(audit, "_count_mutate_token_metrics", dict)
    monkeypatch.setattr(
        audit,
        "_collect_pytest_memberships",
        lambda *_args, **_kwargs: memberships,
    )
    monkeypatch.setattr(
        audit,
        "_collect_base_pytest_memberships",
        lambda _environment: (True, memberships, True, True, None),
    )
    monkeypatch.setattr(audit, "evaluate_pr_delta_metrics", lambda _counts: 0)
    monkeypatch.setattr(
        audit,
        "evaluate_protected_pytest_memberships",
        lambda *_args, **_kwargs: 1,
    )

    assert audit.main() == 1

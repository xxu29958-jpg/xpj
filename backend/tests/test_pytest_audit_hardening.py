from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_packaging_tests
from scripts.packaging_pytest_contract import PACKAGING_SERIAL_MARKER
from scripts.pytest_execution_contract import (
    collect_pytest_snapshot,
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

    def iter_markers_with_node(
        self,
        name: str,
    ) -> tuple[tuple[_ResourceItem, SimpleNamespace], ...]:
        return ((self, self._resource_marker),) if name == self._marker_name else ()

    def get_closest_marker(self, _name: str) -> None:
        return None

    def add_marker(self, _marker: object) -> None:
        return None


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


def test_real_loopback_consumers_stay_in_host_network_lane() -> None:
    serial = collect_pytest_snapshot(
        "packaging/tests",
        mark_expression=PACKAGING_SERIAL_MARKER,
        backend_root=run_packaging_tests.BACKEND_ROOT,
    )
    expected = {
        "packaging/tests/test_backend_bootstrap_contract.py::"
        "test_maintenance_failure_writes_credential_free_durable_result",
        "packaging/tests/test_backend_bootstrap_contract.py::"
        "test_bootstrap_request_bypasses_default_proxy",
        "packaging/tests/test_legacy_installer_security.py::"
        "test_bootstrap_http_exception_revalidates_listener_and_fails_closed",
        "packaging/tests/test_legacy_installer_security.py::"
        "test_bootstrap_requires_owned_listener_and_sends_utf8_json_bytes",
    }
    assert expected.issubset(serial.nodeids)


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
    }


def _write_base_marker_contract(backend_root: Path) -> None:
    scripts = backend_root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "pytest_marker_contract.py").write_text(
        "\n".join(
            (
                "PYTEST_MARKER_CONTRACT_SCHEMA_VERSION = 1",
                'BACKEND_PARALLEL_SAFE_MARKER = "base_parallel_safe"',
                'BACKEND_REAL_DB_MARKER = "base_real_db"',
                'BACKEND_STATEFUL_MARKER = "base_stateful"',
                'BACKEND_CLUSTER_MARKER = "base_cluster"',
                'PACKAGING_PARALLEL_MARKER = "base_packaging_parallel"',
                'PACKAGING_SERIAL_MARKER = "base_packaging_serial"',
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
                if mark_expression in (None, "base_packaging_serial")
                else ()
            )
        return len(nodeids), nodeids

    monkeypatch.setattr(audit, "_collect_pytest_tests", collect)
    contract = audit._load_base_marker_contract(backend_root)
    memberships = audit._collect_pytest_memberships(backend_root, contract)
    assert memberships["packaging_serial"] == (packaging_nodeid,)
    assert set(observed) == {
        "not base_stateful",
        "base_parallel_safe",
        "base_real_db",
        "base_stateful",
        "base_cluster",
        "base_packaging_parallel",
        "base_packaging_serial",
    }

"""Real subprocess tests for worker capacity, retirement and failure ownership."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.log_sanitize import SanitizedFormatter
from app.services.ocr_worker_client import OcrWorkerClient
from ocr_runtime.protocol import OcrRuntimeError

STUB = Path(__file__).with_name("ocr_stub_worker.py")


def _client(**kwargs) -> OcrWorkerClient:
    return OcrWorkerClient(command=[sys.executable, str(STUB)], stop_seconds=0.1,
                           **dict({"timeout_seconds": 3}, **kwargs))


def _wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("process condition did not become true")
        time.sleep(0.01)


def _alive(pid: int) -> bool:
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        # A killed grandchild may briefly be a zombie until its init reaps it.
        status = Path(f"/proc/{pid}/stat")
        return not status.exists() or status.read_text().split()[2] != "Z"
    except ProcessLookupError:
        return False


def test_one_process_reused_then_idle_retires_and_new_generation_starts(tmp_path):
    client = _client(idle_seconds=0.15)
    try:
        first = client.recognize(tmp_path / "ok", "a")
        second = client.recognize(tmp_path / "ok", "b")
        assert first["pid"] == second["pid"]
        _wait(lambda: client.pid is None)
        assert not _alive(first["pid"])
        third = client.recognize(tmp_path / "ok", "c")
        assert third["pid"] != first["pid"]
    finally:
        client.close()


@pytest.mark.parametrize("mode,code", [("exit", "ocr_worker_exited"),
                                     ("wrong-generation", "ocr_protocol_invalid"),
                                     ("oversized", "ocr_protocol_invalid")])
def test_bad_worker_is_retired_before_replacement(tmp_path, mode, code):
    client = _client()
    try:
        pid = client.recognize(tmp_path / "ok", "a")["pid"]
        with pytest.raises(OcrRuntimeError, match=code):
            client.recognize(tmp_path / mode, "b")
        assert client.pid is None and not _alive(pid)
        assert client.recognize(tmp_path / "ok", "c")["pid"] != pid
    finally:
        client.close()


def test_timeout_reaps_descendants_before_slot_can_be_reused(tmp_path):
    client = _client(timeout_seconds=0.3)
    child_file = tmp_path / "hang-child"
    try:
        with pytest.raises(OcrRuntimeError, match="ocr_timeout"):
            client.recognize(child_file, "a")
        child_pid = int(child_file.read_text())
        _wait(lambda: not _alive(child_pid))
        assert client.pid is None
        assert client.recognize(tmp_path / "ok", "b")["input_sha256"] == "b"
    finally:
        client.close()


def test_stop_interrupts_inflight_work_and_does_not_reopen(tmp_path):
    client = _client(timeout_seconds=10)
    child_file = tmp_path / "hang-stop"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.recognize, child_file, "a")
        _wait(child_file.exists)
        pid = client.pid
        child_pid = int(child_file.read_text())
        client.close()
        with pytest.raises(OcrRuntimeError):
            future.result(timeout=3)
        _wait(lambda: not _alive(pid) and not _alive(child_pid))
    with pytest.raises(OcrRuntimeError, match="ocr_stopping"):
        client.recognize(tmp_path / "ok", "a")


def test_concurrent_calls_and_idle_race_keep_one_worker(tmp_path):
    client = _client(idle_seconds=0.2)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: client.recognize(tmp_path / "ok", str(i)), range(12)))
        assert len({result["pid"] for result in results}) == 1
        assert {result["input_sha256"] for result in results} == {str(i) for i in range(12)}
        _wait(lambda: client.pid is None)
    finally:
        client.close()


def test_child_does_not_receive_application_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "test-only-value")
    monkeypatch.setenv("ADMIN_TOKEN", "test-only-value")
    client = _client()
    try:
        assert client.recognize(tmp_path / "ok", "a")["credential_names"] == []
    finally:
        client.close()


def test_unexpected_reader_failure_is_observed_and_owned_process_is_reaped(tmp_path, monkeypatch, caplog):
    def fail_read(*_args):
        raise RuntimeError("token=synthetic-reader-secret")

    monkeypatch.setattr("app.services.ocr_worker_client.read_message", fail_read)
    client = _client()
    try:
        with pytest.raises(OcrRuntimeError, match="ocr_protocol_invalid"):
            client.recognize(tmp_path / "ok", "a")
        assert client.pid is None
        output = "\n".join(SanitizedFormatter().format(record) for record in caplog.records)
        assert "OCR pipe reader failed" in output and "in fail_read" in output
        assert "synthetic-reader-secret" not in output
    finally:
        client.close()


@pytest.mark.parametrize("failure", [RuntimeError("attach failed"), KeyboardInterrupt()])
def test_attachment_failure_reaps_child_and_propagates_original_error(tmp_path, monkeypatch, failure):
    children = []

    def refuse_owner(process):
        children.append(process)
        raise failure

    monkeypatch.setattr("app.services.ocr_worker_client.ProcessTreeOwner", refuse_owner)
    client = _client()
    try:
        with pytest.raises(type(failure)) as raised:
            client.recognize(tmp_path / "ok", "a")
        assert raised.value is failure
        assert len(children) == 1 and children[0].poll() is not None
        assert children[0].stdin.closed and children[0].stdout.closed
        assert client.pid is None
    finally:
        client.close()


def test_idle_retirement_failure_is_reported_and_cannot_reopen_work(tmp_path, monkeypatch, caplog):
    client = _client(idle_seconds=0.2)
    try:
        pid = client.recognize(tmp_path / "ok", "a")["pid"]

        def fail_wait(_timeout):
            raise TimeoutError("token=synthetic-idle-secret")

        with monkeypatch.context() as patch:
            patch.setattr(client._owner, "terminate_and_wait", fail_wait)
            _wait(lambda: any("OCR idle retirement failed" in record.getMessage() for record in caplog.records))
            with pytest.raises(OcrRuntimeError, match="ocr_stopping"):
                client.recognize(tmp_path / "ok", "b")
        _wait(lambda: not _alive(pid))
        output = "\n".join(SanitizedFormatter().format(record) for record in caplog.records)
        assert "in fail_wait" in output and "synthetic-idle-secret" not in output
    finally:
        client.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel Job commit limit")
def test_kernel_refuses_over_budget_allocation_then_worker_can_recover(tmp_path):
    client = _client()
    try:
        pid = client.recognize(tmp_path / "ok", "first")["pid"]
        with pytest.raises(OcrRuntimeError, match="ocr_resource_limit"):
            client.recognize(tmp_path / "over-memory-limit", "limit")
        assert client.pid is None and not _alive(pid)
        assert client.recognize(tmp_path / "ok", "after")["pid"] != pid
    finally:
        client.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel Job ownership contract")
def test_backend_death_closes_job_and_retires_worker(tmp_path):
    code = """
import json, sys, time
from pathlib import Path
from app.services.ocr_worker_client import OcrWorkerClient
client = OcrWorkerClient(command=[sys.executable, sys.argv[1]])
result = client.recognize(Path('ok'), 'digest')
print(json.dumps(result), flush=True)
time.sleep(60)
"""
    parent = subprocess.Popen([sys.executable, "-c", code, str(STUB)],
                              cwd=Path(__file__).resolve().parents[1],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000)
    try:
        # communicate has a deadline; killing this exact parent tests kernel
        # ownership, without a Python finally/atexit running in that parent.
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = json.loads(pool.submit(parent.stdout.readline).result(timeout=10))
        assert _alive(result["pid"])
        parent.kill()
        parent.wait(timeout=5)
        _wait(lambda: not _alive(result["pid"]))
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.communicate(timeout=5)

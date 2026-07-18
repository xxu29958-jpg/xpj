"""Real OS process primitives injected into [BackendSupervisor].

Kept separate from the supervision logic so the latter stays unit-testable: these
functions actually touch the OS (spawn uvicorn, tree-kill, HTTP probe)
and are only exercised by the running app, not the unit tests.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend_manager.version_contract import is_managed_release_version

_CREATE_NO_WINDOW = 0x08000000  # don't pop a console window for child processes
_CREATE_SUSPENDED = 0x00000004
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_LOG_LINES = 300
_HEALTH_RESPONSE_LIMIT_BYTES = 4096
_HEALTH_KEYS = frozenset(
    {
        "contract",
        "status",
        "product",
        "backend_version",
        "installation_id",
        "runtime_access_state",
        "owner_state",
        "owner_recovery_channel",
        "mobile_connectivity",
    },
)
_MOBILE_CONNECTIVITY_KEYS = frozenset(
    {"mobile_endpoint_state", "android_binding_state", "iphone_upload_state"},
)
_MOBILE_ENDPOINT_STATES = frozenset({"local_only", "public_configured_unverified"})
_MOBILE_TASK_STATES = frozenset({"setup_required", "configured_unverified"})
_OWNER_STATES = frozenset({"configured", "recovery_required"})
_OWNER_RECOVERY_CHANNELS = frozenset({"development", "managed_host", "operator"})
_RUNTIME_ACCESS_STATES = frozenset({"available", "repair_required"})
_INSTALLATION_ID_PATTERN = re.compile(r"ticketbox-[0-9a-f]{32}\Z")
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", ctypes.c_ulonglong),
        ("write_operation_count", ctypes.c_ulonglong),
        ("other_operation_count", ctypes.c_ulonglong),
        ("read_transfer_count", ctypes.c_ulonglong),
        ("write_transfer_count", ctypes.c_ulonglong),
        ("other_transfer_count", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_longlong),
        ("per_job_user_time_limit", ctypes.c_longlong),
        ("limit_flags", ctypes.c_ulong),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_ulong),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_ulong),
        ("scheduling_class", ctypes.c_ulong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _BasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_int32),
        ("tpDeltaPri", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
    ]


class WindowsKillOnCloseJob:
    """One owning job handle; Windows kills every assigned descendant when it closes."""

    def __init__(self, handle: int) -> None:
        self._handle = handle

    def close(self) -> None:
        handle, self._handle = self._handle, 0
        if handle:
            kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            kernel32.CloseHandle(handle)

    def __del__(self) -> None:
        self.close()


def _attach_kill_on_close_job(popen: subprocess.Popen[str]) -> WindowsKillOnCloseJob:
    if os.name != "nt":
        raise OSError("Windows Job Object is unavailable on this platform")
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    job = WindowsKillOnCloseJob(handle)
    info = _ExtendedLimitInformation()
    info.basic_limit_information.limit_flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    try:
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        process_handle = getattr(popen, "_handle", None)
        if not process_handle or not kernel32.AssignProcessToJobObject(handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        job.close()
        raise
    return job


def _resume_suspended_process(process_id: int) -> None:
    """Resume the only thread present before a suspended process executes user code."""
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
    kernel32.Thread32First.restype = ctypes.c_int
    kernel32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ThreadEntry32)]
    kernel32.Thread32Next.restype = ctypes.c_int
    kernel32.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenThread.restype = ctypes.c_void_p
    kernel32.ResumeThread.argtypes = [ctypes.c_void_p]
    kernel32.ResumeThread.restype = ctypes.c_uint32
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == process_id:
                thread = kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME,
                    False,
                    entry.th32ThreadID,
                )
                if not thread:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    kernel32.CloseHandle(thread)
                return
            found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    raise RuntimeError("Cannot identify the suspended process primary thread")


def spawn_windows_job_process(
    command: list[str],
    **popen_kwargs: object,
) -> tuple[subprocess.Popen, WindowsKillOnCloseJob]:
    """Create a Windows child suspended, bind its Job authority, then let it run."""
    if os.name != "nt":
        raise OSError("Windows Job Object is unavailable on this platform")
    requested_flags = int(popen_kwargs.pop("creationflags", 0))
    process = subprocess.Popen(
        command,
        creationflags=requested_flags | _CREATE_SUSPENDED,
        **popen_kwargs,
    )
    job: WindowsKillOnCloseJob | None = None
    try:
        job = _attach_kill_on_close_job(process)
        _resume_suspended_process(process.pid)
    except BaseException:
        if job is not None:
            job.close()
        else:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                process.kill()
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            process.wait(timeout=5)
        raise
    return process, job


@dataclass(frozen=True)
class TicketboxHealthExpectation:
    installation_id: str
    backend_version: str | None = None


@dataclass(frozen=True)
class HealthProbeResult:
    state: Literal["healthy", "pending", "mismatch", "stopped"]
    detail: str
    mobile_endpoint_state: str = "unknown"
    android_binding_state: str = "unknown"
    iphone_upload_state: str = "unknown"
    runtime_access_state: str = "unknown"
    owner_state: str = "unknown"
    owner_recovery_channel: str = "unknown"

    @property
    def healthy(self) -> bool:
        return self.state == "healthy"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


class UvicornProcess:
    """A spawned uvicorn process whose stdout/stderr is pumped into a ring buffer.

    Satisfies the ``ManagedProcess`` protocol the supervisor depends on.
    """

    def __init__(self, popen: subprocess.Popen[str], job: WindowsKillOnCloseJob | None = None) -> None:
        self._popen = popen
        self._job = job
        self._log: deque[str] = deque(maxlen=_LOG_LINES)
        self._lock = threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()

    @property
    def pid(self) -> int:
        return self._popen.pid

    def poll(self) -> int | None:
        result = self._popen.poll()
        if result is not None:
            self._close_job()
        return result

    def recent_log(self) -> list[str]:
        with self._lock:
            return list(self._log)

    def wait(self, timeout: float) -> int:
        try:
            result = self._popen.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError from exc
        self._close_job()
        return result

    def terminate_owned(self) -> bool:
        """Terminate this exact owned process tree through its Job handle."""
        if self.poll() is not None:
            return True
        if self._job is None:
            return False
        self._close_job()
        return True

    def _close_job(self) -> None:
        job, self._job = self._job, None
        if job is not None:
            job.close()

    def _pump(self) -> None:
        stream = self._popen.stdout
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            if line:
                with self._lock:
                    self._log.append(line.rstrip())


def spawn_backend(
    *,
    backend_root: Path,
    venv_python: Path,
    data_root: Path,
    host: str,
    port: int,
) -> UvicornProcess:
    """Launch ``uvicorn app.main:app`` from the backend's own venv."""
    child_environment = os.environ.copy()
    child_environment["TICKETBOX_DATA_DIR"] = str(data_root)
    child_environment["XPJ_EXTRA_LOOPBACK_HOSTS"] = f"127.0.0.1:{port}"
    popen, job = spawn_windows_job_process(
        [
            str(venv_python), "-m", "uvicorn", "app.main:app",
            "--host", host, "--port", str(port), "--no-access-log",
        ],
        cwd=str(backend_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATE_NO_WINDOW,
        env=child_environment,
    )
    return UvicornProcess(popen, job)


def tree_kill(pid: int) -> bool:
    """Force-kill a process AND its descendants (``/T``).

    uvicorn's worker is a child process; killing only the parent would orphan the
    worker (still bound to the port). ``taskkill /T`` takes down the whole tree, so a
    stop actually frees the port.
    """
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0


def _validate_health_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/api/health/installation"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("健康检查 URL 不符合固定 loopback 身份契约。")
    if parsed.port is None:
        raise ValueError("健康检查 URL 缺少端口。")


def _parse_health_payload(raw: bytes, expectation: TicketboxHealthExpectation) -> HealthProbeResult:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return HealthProbeResult("mismatch", "loopback 响应不是有效的 Ticketbox JSON。")
    if not isinstance(decoded, dict) or set(decoded) != _HEALTH_KEYS:
        return HealthProbeResult("mismatch", "loopback JSON 不符合 Ticketbox 身份字段契约。")
    if decoded.get("status") != "ok" or decoded.get("product") != "ticketbox":
        return HealthProbeResult("mismatch", "loopback 服务不是 Ticketbox 后端。")
    if decoded.get("contract") != "ticketbox-installation-health-v2":
        return HealthProbeResult("mismatch", "Ticketbox 安装健康合同版本不匹配。")
    version = decoded.get("backend_version")
    installation_id = decoded.get("installation_id")
    if not is_managed_release_version(version):
        return HealthProbeResult("mismatch", "Ticketbox 后端版本身份无效。")
    if not isinstance(installation_id, str) or not _INSTALLATION_ID_PATTERN.fullmatch(installation_id):
        return HealthProbeResult("mismatch", "Ticketbox 安装身份无效。")
    if expectation.backend_version is not None and version != expectation.backend_version:
        return HealthProbeResult("mismatch", "运行中的 Ticketbox 版本与安装记录不一致。")
    if installation_id != expectation.installation_id:
        return HealthProbeResult("mismatch", "运行中的 Ticketbox 实例与本机安装记录不一致。")
    runtime_access_state = decoded.get("runtime_access_state")
    if runtime_access_state not in _RUNTIME_ACCESS_STATES:
        return HealthProbeResult("mismatch", "Ticketbox 运行访问字段合同无效。")
    owner_state = decoded.get("owner_state")
    owner_recovery_channel = decoded.get("owner_recovery_channel")
    if owner_state not in _OWNER_STATES or owner_recovery_channel not in _OWNER_RECOVERY_CHANNELS:
        return HealthProbeResult("mismatch", "Ticketbox 拥有者恢复字段合同无效。")
    mobile = decoded.get("mobile_connectivity")
    if not isinstance(mobile, dict) or set(mobile) != _MOBILE_CONNECTIVITY_KEYS:
        return HealthProbeResult("mismatch", "Ticketbox 移动端能力字段合同无效。")
    endpoint_state = mobile.get("mobile_endpoint_state")
    android_state = mobile.get("android_binding_state")
    iphone_state = mobile.get("iphone_upload_state")
    if (
        endpoint_state not in _MOBILE_ENDPOINT_STATES
        or android_state not in _MOBILE_TASK_STATES
        or iphone_state not in _MOBILE_TASK_STATES
        or (endpoint_state == "local_only" and (android_state != "setup_required" or iphone_state != "setup_required"))
        or (
            endpoint_state == "public_configured_unverified"
            and (android_state != "configured_unverified" or iphone_state != "configured_unverified")
        )
    ):
        return HealthProbeResult("mismatch", "Ticketbox 移动端能力组合不符合部署合同。")
    if runtime_access_state == "repair_required":
        detail = "Ticketbox 后端身份已验证，但安装维护尚未完成。"
    elif owner_state == "recovery_required":
        detail = "Ticketbox 后端身份已验证，但缺少可用拥有者身份。"
    else:
        detail = "Ticketbox 产品、版本、安装身份和拥有者身份已验证。"
    return HealthProbeResult(
        "healthy",
        detail,
        mobile_endpoint_state=endpoint_state,
        android_binding_state=android_state,
        iphone_upload_state=iphone_state,
        runtime_access_state=runtime_access_state,
        owner_state=owner_state,
        owner_recovery_channel=owner_recovery_channel,
    )


def probe_ticketbox_health(
    url: str,
    *,
    expectation: TicketboxHealthExpectation,
    timeout: float,
) -> HealthProbeResult:
    try:
        _validate_health_url(url)
    except ValueError as exc:
        return HealthProbeResult("mismatch", str(exc))
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Host": "127.0.0.1"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310 - validated fixed loopback URL
            if response.status != 200:
                return HealthProbeResult("pending", f"Ticketbox 后端尚未就绪（HTTP {response.status}）。")
            media_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
            if media_type != "application/json":
                return HealthProbeResult("mismatch", "loopback 200 响应不是 Ticketbox JSON。")
            raw = response.read(_HEALTH_RESPONSE_LIMIT_BYTES + 1)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return HealthProbeResult("pending", f"Ticketbox 后端身份检查等待中（{type(exc).__name__}）。")
    if len(raw) > _HEALTH_RESPONSE_LIMIT_BYTES:
        return HealthProbeResult("mismatch", "loopback 健康响应超过 Ticketbox 上限。")
    return _parse_health_payload(raw, expectation)


def health_ok(
    url: str,
    *,
    expectation: TicketboxHealthExpectation,
    timeout: float,
) -> bool:
    return probe_ticketbox_health(url, expectation=expectation, timeout=timeout).healthy

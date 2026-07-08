"""T27: Read-only Windows scheduled task status for the Owner Console.

This module surfaces the status of the scheduled tasks the Windows host runs
(backend service, Cloudflare tunnel, daily backup, public boundary check) so
the owner can spot when something has stopped without opening Task Scheduler.

Strictly read-only: we never create, modify, start, or stop tasks from the
Web/Owner UI. The implementation is platform-aware and gracefully degrades
to an empty list on non-Windows hosts or when ``schtasks.exe`` is missing.
"""

from __future__ import annotations

import csv
import io
import os
import re
import subprocess  # noqa: S404 - read-only schtasks query, fixed task names
import sys
import time
from dataclasses import dataclass

# Default task names installed by ``scripts/install_*.ps1``. Owners can
# override the list via ``XPJ_WINDOWS_TASK_NAMES`` (comma-separated) when
# they renamed the tasks during installation.
_DEFAULT_TASKS: tuple[str, ...] = (
    "TicketboxBackend",
    "TicketboxCloudflareTunnel",
    "TicketboxBackup",
    "TicketboxBoundaryCheck",
)

_CACHE_TTL_SECONDS = 30.0
_QUERY_TIMEOUT_SECONDS = 3.0

_TASK_SCHEDULER_INFO_RESULTS: dict[int, str] = {
    0: "成功",
    0x41300: "任务已准备好",
    0x41301: "任务正在运行",
    0x41302: "任务已禁用",
    0x41303: "任务尚未运行",
    0x41304: "没有更多计划运行时间",
    0x41305: "一个或多个任务属性尚未设置",
    0x41306: "任务已由用户终止",
    0x41307: "任务没有触发器或触发器已禁用",
    0x41308: "事件触发器没有设置运行时间",
}


@dataclass
class TaskStatusVM:
    """View-model for a single Windows scheduled task.

    Fields mirror the schtasks CSV columns we surface in the Owner UI.
    ``available`` is ``False`` when the task could not be queried (missing,
    permission denied, schtasks not found, non-Windows host).
    """

    name: str
    available: bool
    status: str  # Ready / Running / Disabled / Could Not Start / Unknown
    last_run: str
    last_result: str
    next_run: str
    note: str = ""
    last_result_failed: bool = False


class _TaskStatusCache:
    """Short-lived process cache for expensive schtasks queries."""

    def __init__(self) -> None:
        self._entry: tuple[float, list[TaskStatusVM]] | None = None

    def fresh_rows(self, now: float) -> list[TaskStatusVM] | None:
        if self._entry is None or now - self._entry[0] >= _CACHE_TTL_SECONDS:
            return None
        return list(self._entry[1])

    def store(self, now: float, rows: list[TaskStatusVM]) -> None:
        self._entry = (now, rows)

    def reset(self) -> None:
        self._entry = None


_TASK_STATUS_CACHE = _TaskStatusCache()


def _task_names() -> tuple[str, ...]:
    raw = os.environ.get("XPJ_WINDOWS_TASK_NAMES", "").strip()
    if not raw:
        return _DEFAULT_TASKS
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else _DEFAULT_TASKS


def _parse_last_result(value: str) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    match = re.search(r"0x[0-9a-fA-F]+|-?\d+", raw)
    if match is None:
        return None
    token = match.group(0)
    try:
        if token.lower().startswith("0x"):
            return int(token, 16)
        return int(token, 10)
    except ValueError:
        return None


def _last_result_note(value: str) -> str:
    code = _parse_last_result(value)
    if code is None:
        return ""
    if code == 0:
        return ""
    note = _TASK_SCHEDULER_INFO_RESULTS.get(code)
    if note is not None:
        return f"信息码：{note}"
    return f"上次运行返回非零结果：{value}"


def _last_result_failed(value: str) -> bool:
    code = _parse_last_result(value)
    if code is None:
        return False
    return code not in _TASK_SCHEDULER_INFO_RESULTS


def _unavailable_task_status(task_name: str, note: str) -> TaskStatusVM:
    return TaskStatusVM(
        name=task_name,
        available=False,
        status="Unknown",
        last_run="",
        last_result="",
        next_run="",
        note=note,
    )


def _query_schtasks(task_name: str) -> subprocess.CompletedProcess[bytes] | TaskStatusVM:
    try:
        return subprocess.run(  # noqa: S603 - args fixed, task_name from allow-list
            ["schtasks.exe", "/Query", "/TN", task_name, "/FO", "CSV", "/V"],
            capture_output=True,
            timeout=_QUERY_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return _unavailable_task_status(task_name, "未找到 schtasks.exe")
    except subprocess.TimeoutExpired:
        return _unavailable_task_status(task_name, "查询超时")
    except OSError as exc:
        return _unavailable_task_status(
            task_name,
            f"查询失败：{exc.strerror or exc.__class__.__name__}",
        )


def _decode_schtasks_stdout(raw: bytes | str) -> str:
    if not isinstance(raw, bytes):
        return raw
    for codec in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(codec)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _first_schtasks_row(task_name: str, text: str) -> dict[str, str] | TaskStatusVM:
    reader = csv.DictReader(io.StringIO(text))
    try:
        return next(reader)
    except StopIteration:
        return _unavailable_task_status(task_name, "schtasks 无返回行")


def _task_status_from_row(task_name: str, row: dict[str, str]) -> TaskStatusVM:
    last_result = row.get("Last Result", "").strip()
    return TaskStatusVM(
        name=task_name,
        available=True,
        status=row.get("Status", "").strip() or "Unknown",
        last_run=row.get("Last Run Time", "").strip(),
        last_result=last_result,
        next_run=row.get("Next Run Time", "").strip(),
        note=_last_result_note(last_result),
        last_result_failed=_last_result_failed(last_result),
    )


def _query_one(task_name: str) -> TaskStatusVM:
    if sys.platform != "win32":
        return _unavailable_task_status(task_name, "非 Windows 主机")
    proc = _query_schtasks(task_name)
    if isinstance(proc, TaskStatusVM):
        return proc
    if proc.returncode != 0:
        return _unavailable_task_status(task_name, "未注册或无权限")
    # Decode tolerantly: schtasks may emit GBK on zh-CN Windows hosts.
    row = _first_schtasks_row(task_name, _decode_schtasks_stdout(proc.stdout))
    if isinstance(row, TaskStatusVM):
        return row
    return _task_status_from_row(task_name, row)


def list_windows_tasks(*, force_refresh: bool = False) -> list[TaskStatusVM]:
    """Return the latest status of the configured scheduled tasks.

    Cached for 30 seconds because schtasks spawns a process and the Owner
    index re-renders frequently while the operator inspects it.
    """
    now = time.monotonic()
    if not force_refresh:
        cached_rows = _TASK_STATUS_CACHE.fresh_rows(now)
        if cached_rows is not None:
            return cached_rows
    rows = [_query_one(name) for name in _task_names()]
    _TASK_STATUS_CACHE.store(now, rows)
    return list(rows)


def reset_cache() -> None:
    """Test helper: clear the in-process status cache."""
    _TASK_STATUS_CACHE.reset()

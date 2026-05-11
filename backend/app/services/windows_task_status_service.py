"""T27: Read-only Windows scheduled task status for the Owner Console.

This module surfaces the status of the three scheduled tasks the v0.4
Windows host runs (backend service, Cloudflare tunnel, daily backup) so the
owner can spot when something has stopped without opening Task Scheduler.

Strictly read-only: we never create, modify, start, or stop tasks from the
Web/Owner UI. The implementation is platform-aware and gracefully degrades
to an empty list on non-Windows hosts or when ``schtasks.exe`` is missing.
"""

from __future__ import annotations

import csv
import io
import os
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
)

_CACHE_TTL_SECONDS = 30.0
_QUERY_TIMEOUT_SECONDS = 3.0


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


def _task_names() -> tuple[str, ...]:
    raw = os.environ.get("XPJ_WINDOWS_TASK_NAMES", "").strip()
    if not raw:
        return _DEFAULT_TASKS
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else _DEFAULT_TASKS


_cache: tuple[float, list[TaskStatusVM]] | None = None


def _query_one(task_name: str) -> TaskStatusVM:
    if sys.platform != "win32":
        return TaskStatusVM(
            name=task_name,
            available=False,
            status="Unknown",
            last_run="",
            last_result="",
            next_run="",
            note="非 Windows 主机",
        )
    try:
        proc = subprocess.run(  # noqa: S603 - args fixed, task_name from allow-list
            ["schtasks.exe", "/Query", "/TN", task_name, "/FO", "CSV", "/V"],
            capture_output=True,
            timeout=_QUERY_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return TaskStatusVM(
            name=task_name,
            available=False,
            status="Unknown",
            last_run="",
            last_result="",
            next_run="",
            note="未找到 schtasks.exe",
        )
    except subprocess.TimeoutExpired:
        return TaskStatusVM(
            name=task_name,
            available=False,
            status="Unknown",
            last_run="",
            last_result="",
            next_run="",
            note="查询超时",
        )
    except OSError as exc:
        return TaskStatusVM(
            name=task_name,
            available=False,
            status="Unknown",
            last_run="",
            last_result="",
            next_run="",
            note=f"查询失败：{exc.strerror or exc.__class__.__name__}",
        )
    if proc.returncode != 0:
        return TaskStatusVM(
            name=task_name,
            available=False,
            status="Unknown",
            last_run="",
            last_result="",
            next_run="",
            note="未注册或无权限",
        )
    # Decode tolerantly: schtasks may emit GBK on zh-CN Windows hosts.
    raw = proc.stdout
    if isinstance(raw, bytes):
        for codec in ("utf-8", "gbk", "mbcs"):
            try:
                text = raw.decode(codec)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    reader = csv.DictReader(io.StringIO(text))
    try:
        row = next(reader)
    except StopIteration:
        return TaskStatusVM(
            name=task_name,
            available=False,
            status="Unknown",
            last_run="",
            last_result="",
            next_run="",
            note="schtasks 无返回行",
        )
    return TaskStatusVM(
        name=task_name,
        available=True,
        status=row.get("Status", "").strip() or "Unknown",
        last_run=row.get("Last Run Time", "").strip(),
        last_result=row.get("Last Result", "").strip(),
        next_run=row.get("Next Run Time", "").strip(),
    )


def list_windows_tasks(*, force_refresh: bool = False) -> list[TaskStatusVM]:
    """Return the latest status of the configured scheduled tasks.

    Cached for 30 seconds because schtasks spawns a process and the Owner
    index re-renders frequently while the operator inspects it.
    """
    global _cache
    now = time.monotonic()
    if not force_refresh and _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return list(_cache[1])
    rows = [_query_one(name) for name in _task_names()]
    _cache = (now, rows)
    return list(rows)


def reset_cache() -> None:
    """Test helper: clear the in-process status cache."""
    global _cache
    _cache = None

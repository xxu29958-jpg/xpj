from __future__ import annotations

import os

from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.command import (
    CommandRunner,
    SubprocessCommandRunner,
    require_ok,
)


def service_registered(name: str) -> bool:
    if os.name != "nt":
        return False
    return service_exists(SubprocessCommandRunner(), name)


def service_exists(runner: CommandRunner, name: str) -> bool:
    completed = runner.run(["sc.exe", "query", name])
    if completed.returncode == 0:
        return True
    if completed.returncode == 1060:
        return False
    require_ok(completed, code="service_query_failed")
    raise AssertionError("require_ok must raise for a failed service query")


def service_running(runner: CommandRunner, name: str) -> bool:
    completed = runner.run(["sc.exe", "query", name])
    return completed.returncode == 0 and "RUNNING" in completed.stdout.upper()


def require_service(runner: CommandRunner, name: str) -> None:
    if not service_exists(runner, name):
        raise LifecycleError("postcondition_missing", f"service {name} is not registered")


def require_running_service(runner: CommandRunner, name: str) -> None:
    if not service_running(runner, name):
        raise LifecycleError("postcondition_missing", f"service {name} is not RUNNING")


def start_service(runner: CommandRunner, name: str, *, code: str) -> None:
    completed = runner.run(["sc.exe", "start", name])
    combined = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode == 0 or "1056" in combined or "already been started" in combined.lower():
        return
    require_ok(completed, code=code)


def stop_service(runner: CommandRunner, name: str, *, code: str) -> None:
    completed = runner.run(["sc.exe", "stop", name])
    combined = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode == 0 or "1062" in combined or "not been started" in combined.lower():
        return
    require_ok(completed, code=code)


def scm_query_state(runner: CommandRunner, name: str) -> str:
    completed = runner.run(["sc.exe", "query", name])
    text = f"{completed.stdout}\n{completed.stderr}".upper()
    for token in ("START_PENDING", "STOP_PENDING", "RUNNING", "STOPPED"):
        if token in text:
            return token
    return "UNKNOWN"

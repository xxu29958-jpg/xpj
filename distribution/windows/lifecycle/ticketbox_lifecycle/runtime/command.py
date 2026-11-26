from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ticketbox_lifecycle.errors import LifecycleError


@dataclass(frozen=True)
class CompletedCommand:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> CompletedCommand: ...


class _SubprocessManagedJob:
    def __init__(self) -> None:
        self._job: object | None = None

    def __enter__(self) -> _SubprocessManagedJob:
        from ticketbox_lifecycle.runtime.windows_process import PersistentKillOnCloseJob

        try:
            self._job = PersistentKillOnCloseJob()
        except OSError as exc:
            raise LifecycleError(
                "command_start_failed",
                "managed Windows process job could not be created",
            ) from exc
        return self

    def run_background_starter(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_s: int = 120,
        on_timeout: Callable[[], None] | None = None,
    ) -> CompletedCommand:
        if not argv:
            raise LifecycleError("empty_command", "adapter refused an empty platform command")
        if self._job is None:
            raise LifecycleError("command_start_failed", "managed Windows process job is not active")
        from ticketbox_lifecycle.runtime.windows_process import ProcessTerminationUnconfirmedError

        program = os.path.basename(str(argv[0])) or "platform command"
        try:
            completed = self._job.run(  # type: ignore[attr-defined]
                argv,
                env=env,
                timeout_s=timeout_s,
                input_text=None,
                capture_output=False,
                on_timeout=on_timeout,
            )
        except ProcessTerminationUnconfirmedError as exc:
            raise LifecycleError(
                "starter_process_not_exited",
                f"{program} did not confirm exit after timeout termination",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LifecycleError(
                "command_outcome_unknown",
                f"{program} did not finish within {timeout_s}s; its external outcome must be re-observed",
            ) from exc
        except OSError as exc:
            raise LifecycleError(
                "command_start_failed",
                f"{program} could not be started",
            ) from exc
        return CompletedCommand(
            argv=tuple(str(part) for part in argv),
            returncode=int(completed.returncode),
            stdout="",
            stderr="",
        )

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        job, self._job = self._job, None
        if job is not None:
            job.close()  # type: ignore[attr-defined]


class SubprocessCommandRunner:
    def open_managed_job(self) -> _SubprocessManagedJob:
        return _SubprocessManagedJob()

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout_s: int = 120,
        input_text: str | None = None,
    ) -> CompletedCommand:
        if not argv:
            raise LifecycleError("empty_command", "adapter refused an empty platform command")
        from ticketbox_lifecycle.runtime.windows_process import ProcessTerminationUnconfirmedError

        program = os.path.basename(str(argv[0])) or "platform command"
        try:
            completed = _run_process(
                argv,
                env=env,
                timeout_s=timeout_s,
                input_text=input_text,
            )
        except ProcessTerminationUnconfirmedError as exc:
            raise LifecycleError(
                "command_termination_unconfirmed",
                f"{program} did not confirm exit after timeout",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LifecycleError(
                "command_outcome_unknown",
                f"{program} did not finish within {timeout_s}s; its external outcome must be re-observed",
            ) from exc
        except OSError as exc:
            raise LifecycleError(
                "command_start_failed",
                f"{program} could not be started",
            ) from exc
        return CompletedCommand(
            argv=tuple(str(part) for part in argv),
            returncode=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


def _run_process(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None,
    timeout_s: int,
    input_text: str | None,
) -> subprocess.CompletedProcess[str]:
    from ticketbox_lifecycle.runtime.windows_process import run_windows_process

    return run_windows_process(
        argv,
        env=env,
        timeout_s=timeout_s,
        input_text=input_text,
    )


def sealed_postgres_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PG")
    }


def sealed_pg_env(passfile: str) -> dict[str, str]:
    env = sealed_postgres_env()
    env["PGPASSFILE"] = passfile
    return env


def require_ok(completed: CompletedCommand, *, code: str) -> CompletedCommand:
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or f"exit={completed.returncode}"
        raise LifecycleError(code, detail)
    return completed

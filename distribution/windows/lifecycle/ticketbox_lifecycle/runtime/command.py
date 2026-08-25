from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
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


class SubprocessCommandRunner:
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
        program = os.path.basename(str(argv[0])) or "platform command"
        try:
            completed = subprocess.run(
                list(argv),
                check=False,
                capture_output=True,
                text=True,
                env=dict(env) if env is not None else None,
                timeout=timeout_s,
                input=input_text,
            )
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

"""Shared PostgreSQL backup validation (ADR-0041 phase-2).

After the SQLite→PostgreSQL cut-over the Owner Console and the scheduled task
produce ``pg_dump -Fc`` custom-format archives; this module is the single
contract for "is this file a restorable Ticketbox dump".

File-level validation is deliberately shallow: ``pg_restore --list`` parses and
lists the archive's table of contents **without a running server**, so a
non-empty listing proves the file is a well-formed, readable pg_dump archive.
Deeper guarantees — every required table present, the rows actually load, the
recorded ``backend_version`` — require a real restore into a scratch database
and are the recovery drill's job (``scripts``/CI), not a file-level check.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path


class PostgresBackupValidationError(RuntimeError):
    """Raised when a file is not a restorable Ticketbox pg_dump archive."""


class PostgresBackupToolError(PostgresBackupValidationError):
    """pg_restore itself could not produce a verdict (missing binary / launch
    failure / timeout) — transient; says nothing about the archive's health.
    Subclasses the validation error so existing ``except`` sites are unaffected
    (PR #253 R4-3: status surfaces must not cache this as "archive invalid")."""


# Windows installs often keep client tools below the machine's ProgramFiles root
# without putting them on PATH. Keep the resolved root injectable for tests, but
# never assume the system drive or an English absolute path.
_PROGRAM_FILES = os.getenv("PROGRAMFILES")
_PG_INSTALL_ROOT: Path | None = (
    Path(_PROGRAM_FILES) / "PostgreSQL" if _PROGRAM_FILES else None
)
_PG_RESTORE_LIST_TIMEOUT_SECONDS = 60


def _install_version_key(binary_path: Path) -> tuple[int, ...]:
    """Numeric sort key from the install dir name (``…\\PostgreSQL\\17\\bin\\x.exe``
    → ``(17,)``, ``9.6`` → ``(9, 6)``). A plain string sort picks 9.x over 17
    ("9" > "1" lexicographically); unparsable names sort lowest so any real
    versioned install wins over them."""
    parts = re.findall(r"\d+", binary_path.parents[1].name)
    if not parts:
        return (-1,)
    return tuple(int(part) for part in parts)


def find_pg_binary(name: str, env_var: str) -> str | None:
    """Resolve a PostgreSQL client binary: env override → PATH → newest install.

    Shared discovery chain for the explicit installed backup owner and CI
    recovery drill; ``None`` when the binary cannot be found anywhere.
    """
    override = os.getenv(env_var)
    if override:
        return override
    located = shutil.which(name)
    if located:
        return located
    candidates = (
        sorted(
            _PG_INSTALL_ROOT.glob(f"*/bin/{name}.exe"),
            key=_install_version_key,
            reverse=True,
        )
        if _PG_INSTALL_ROOT is not None
        else []
    )
    if candidates:
        return str(candidates[0])
    return None


def _pg_restore_binary() -> str:
    """Locate ``pg_restore`` (``PG_RESTORE_PATH`` override → PATH → install glob)."""
    binary = find_pg_binary("pg_restore", "PG_RESTORE_PATH")
    if not binary:
        raise PostgresBackupToolError(
            "pg_restore not found; install the PostgreSQL client tools or set PG_RESTORE_PATH"
        )
    return binary


def validate_postgres_backup_file_with_tool(
    path: Path | str,
    *,
    pg_restore_binary: Path | str,
) -> None:
    """Raise :class:`PostgresBackupValidationError` unless ``path`` is a readable
    pg_dump custom-format archive (``pg_restore --list`` succeeds, non-empty)."""
    dump_path = Path(path)
    if not dump_path.is_file():
        raise PostgresBackupValidationError(f"backup file does not exist: {dump_path}")

    try:
        result = subprocess.run(  # noqa: S603 (binary resolved from PATH/override, fixed args)
            [str(Path(pg_restore_binary).resolve(strict=True)), "--list", str(dump_path)],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=_PG_RESTORE_LIST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PostgresBackupToolError("pg_restore --list timed out") from exc
    except OSError as exc:
        raise PostgresBackupToolError(f"pg_restore could not run: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        raise PostgresBackupValidationError(
            "pg_restore --list failed: " + (detail[-1] if detail else f"exit {result.returncode}")
        )
    if not result.stdout.strip():
        raise PostgresBackupValidationError("pg_restore --list produced an empty table of contents")


def validate_postgres_backup_file(path: Path | str) -> None:
    """CLI/read-only compatibility entrypoint with local tool discovery.

    Production backup owners use :func:`validate_postgres_backup_file_with_tool`
    so the selected binary is an explicit, provenance-bound input.
    """

    validate_postgres_backup_file_with_tool(
        path,
        pg_restore_binary=_pg_restore_binary(),
    )


def is_postgres_backup_valid(path: Path | str) -> bool:
    try:
        validate_postgres_backup_file(path)
    except PostgresBackupValidationError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a restorable Ticketbox pg_dump archive.")
    parser.add_argument("path")
    args = parser.parse_args(argv)
    try:
        validate_postgres_backup_file(args.path)
    except PostgresBackupValidationError as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

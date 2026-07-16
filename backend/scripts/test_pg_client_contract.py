"""PostgreSQL 17 client capability checks for the test authentication contract."""

from __future__ import annotations

import re
import subprocess
from functools import cache

import psycopg

_MINIMUM_REQUIRE_AUTH_VERSION = 170000
_POSTGRES_VERSION = re.compile(
    r"\bPostgreSQL\)?\s+(?P<major>\d+)(?:\.\d+)*\b",
    re.IGNORECASE,
)


@cache
def assert_python_libpq_supports_required_auth() -> None:
    """Require the libpq actually loaded by psycopg to support require_auth."""

    version = psycopg.pq.version()
    if version < _MINIMUM_REQUIRE_AUTH_VERSION:
        raise RuntimeError(
            "Test PostgreSQL requires psycopg to load libpq 17 or newer "
            f"(actual numeric version={version})."
        )


@cache
def assert_postgres_client_supports_required_auth(
    binary: str,
    *,
    label: str,
) -> None:
    """Require one concrete pg client binary to be PostgreSQL 17 or newer."""

    result = subprocess.run(
        [binary, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )
    output = f"{result.stdout}\n{result.stderr}"
    match = _POSTGRES_VERSION.search(output)
    if result.returncode != 0 or match is None:
        raise RuntimeError(f"Could not verify the {label} client version.")
    if int(match.group("major")) < 17:
        raise RuntimeError(f"{label} must be PostgreSQL 17 or newer for require_auth.")

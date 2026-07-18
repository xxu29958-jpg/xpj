from __future__ import annotations

import argparse
import json
import os
import re
import tomllib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

PAYLOAD_TTL_SECONDS = 24 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
DEPENDENCY_CHECK_H2_SCHEMA_EPOCH = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_APP_REFERENCES = frozenset(
    {
        "app:grayDebugRuntimeClasspath",
        "app:grayReleaseRuntimeClasspath",
        "app:internalDebugRuntimeClasspath",
        "app:internalReleaseRuntimeClasspath",
    }
)
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def version_catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "gradle" / "libs.versions.toml"


def dependency_check_version(catalog_path: Path) -> str:
    with catalog_path.open("rb") as stream:
        catalog = tomllib.load(stream)
    plugins = catalog.get("plugins")
    plugin = (
        plugins.get("owasp-dependency-check")
        if isinstance(plugins, dict)
        else None
    )
    version = plugin.get("version") if isinstance(plugin, dict) else None
    if (
        not isinstance(version, str)
        or _VERSION_PATTERN.fullmatch(version) is None
    ):
        raise ValueError("dependency-check plugin version is missing or invalid")
    return version


def dependency_check_cache_abi(catalog_path: Path) -> str:
    version = dependency_check_version(catalog_path)
    major = version.partition(".")[0]
    if not major.isdigit() or int(major) < 1:
        raise ValueError("dependency-check plugin major version is invalid")
    return f"dc{major}-h2e{DEPENDENCY_CHECK_H2_SCHEMA_EPOCH}"


def require_mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def require_nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def require_integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def load_json(path: Path, *, label: str) -> dict[str, Any]:
    return require_mapping(
        json.loads(path.read_text(encoding="utf-8")),
        label=label,
    )


def parse_timestamp(value: object, *, label: str) -> datetime:
    text = require_nonempty_string(value, label=label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def assert_secret_absent() -> None:
    if os.environ.get("NVD_API_KEY"):
        raise ValueError("NVD credential reached a read-only verification process")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-abi",
        action="store_true",
        help="print the Dependency-Check/H2 cache compatibility identity",
    )
    parser.add_argument(
        "--version-catalog",
        type=Path,
        default=version_catalog_path(),
    )
    args = parser.parse_args(argv)
    if not args.cache_abi:
        parser.error("one output mode is required")
    print(dependency_check_cache_abi(args.version_catalog))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

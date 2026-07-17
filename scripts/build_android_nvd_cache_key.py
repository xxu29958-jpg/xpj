from __future__ import annotations

import os
import re
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_INTEGER = re.compile(r"^[1-9][0-9]*$")
_CACHE_CONTRACT = "schema1"
_GITHUB_RUNNER_OSES = frozenset({"Linux", "Windows", "macOS"})


def _validated_component(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing or is not a string")
    text = value.strip()
    if _COMPONENT.fullmatch(text) is None:
        raise ValueError(f"{label} is missing or is not a safe cache-key component")
    return text


def _dependency_check_version(repository_root: Path) -> str:
    catalog_path = repository_root / "android" / "gradle" / "libs.versions.toml"
    with catalog_path.open("rb") as stream:
        catalog = tomllib.load(stream)
    plugins = catalog.get("plugins")
    plugin = (
        plugins.get("owasp-dependency-check")
        if isinstance(plugins, dict)
        else None
    )
    version = plugin.get("version") if isinstance(plugin, dict) else None
    return _validated_component(version, label="dependency-check plugin version")


def build_cache_identity(
    *,
    repository_root: Path,
    runner_os: str,
    run_id: str,
    run_attempt: str,
    date_utc: str,
) -> tuple[str, str, str]:
    normalized_os = _validated_component(runner_os, label="runner OS")
    if normalized_os not in _GITHUB_RUNNER_OSES:
        raise ValueError("runner OS is not a supported GitHub runner identity")
    if _INTEGER.fullmatch(run_id) is None or _INTEGER.fullmatch(run_attempt) is None:
        raise ValueError("GitHub run identity is missing or invalid")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date_utc) is None:
        raise ValueError("UTC cache date is invalid")
    version = _dependency_check_version(repository_root)
    generation = f"dc-{version}-{_CACHE_CONTRACT}"
    suffix = (
        f"{normalized_os}-{generation}-{date_utc}-"
        f"{run_id}-{run_attempt}"
    )
    trusted_key = f"nvd-{suffix}"
    staging_key = f"nvd-staging-{suffix}"
    return generation, trusted_key, staging_key


def main() -> int:
    repository_root = Path(
        os.environ.get("REPOSITORY_ROOT", Path.cwd())
    ).resolve()
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_path:
        raise ValueError("GITHUB_OUTPUT is required")
    date_utc = datetime.now(UTC).strftime("%Y-%m-%d")
    generation, trusted_key, staging_key = build_cache_identity(
        repository_root=repository_root,
        runner_os=os.environ.get("CACHE_OS", ""),
        run_id=os.environ.get("RUN_ID", ""),
        run_attempt=os.environ.get("RUN_ATTEMPT", ""),
        date_utc=date_utc,
    )
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"date={date_utc}\n")
        stream.write(f"generation={generation}\n")
        stream.write(f"value={trusted_key}\n")
        stream.write(f"staging-value={staging_key}\n")
    print(f"Android NVD cache generation: {generation}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

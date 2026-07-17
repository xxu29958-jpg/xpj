from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_INTEGER = re.compile(r"^[1-9][0-9]*$")
_PAYLOAD_SCHEMA = "schema2"
_GITHUB_RUNNER_OSES = frozenset({"Linux", "Windows", "macOS"})


def _validated_component(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing or is not a string")
    text = value.strip()
    if _COMPONENT.fullmatch(text) is None:
        raise ValueError(f"{label} is missing or is not a safe cache-key component")
    return text


def _contract_functions(repository_root: Path):
    scripts = repository_root / "android" / "scripts"
    sys.path.insert(0, str(scripts))
    from dependency_check_contract import (  # noqa: PLC0415
        dependency_check_version,
        producer_contract_sha256,
    )

    return dependency_check_version, producer_contract_sha256


def build_publication_identity(
    *,
    repository_root: Path,
    runner_os: str,
    run_id: str,
    run_attempt: str,
) -> tuple[str, str, str, str, str]:
    normalized_os = _validated_component(runner_os, label="runner OS")
    if normalized_os not in _GITHUB_RUNNER_OSES:
        raise ValueError("runner OS is not a supported GitHub runner identity")
    if _INTEGER.fullmatch(run_id) is None or _INTEGER.fullmatch(run_attempt) is None:
        raise ValueError("GitHub run identity is missing or invalid")
    dependency_check_version, producer_contract_sha256 = _contract_functions(
        repository_root
    )
    catalog = repository_root / "android" / "gradle" / "libs.versions.toml"
    version = _validated_component(
        dependency_check_version(catalog),
        label="dependency-check plugin version",
    )
    contract_digest = producer_contract_sha256(repository_root)
    generation = f"dc-{version}-{_PAYLOAD_SCHEMA}-{contract_digest}"
    suffix = f"{normalized_os}-{generation}-{run_id}-{run_attempt}"
    artifact_name = f"android-nvd-{suffix}"
    artifact_prefix = f"android-nvd-{normalized_os}-{generation}-"
    staging_key = f"nvd-staging-{suffix}"
    return (
        generation,
        contract_digest,
        artifact_name,
        artifact_prefix,
        staging_key,
    )


def main() -> int:
    repository_root = Path(
        os.environ.get("REPOSITORY_ROOT", Path.cwd())
    ).resolve()
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not output_path:
        raise ValueError("GITHUB_OUTPUT is required")
    (
        generation,
        contract_digest,
        artifact_name,
        artifact_prefix,
        staging_key,
    ) = build_publication_identity(
        repository_root=repository_root,
        runner_os=os.environ.get("CACHE_OS", ""),
        run_id=os.environ.get("RUN_ID", ""),
        run_attempt=os.environ.get("RUN_ATTEMPT", ""),
    )
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"generation={generation}\n")
        stream.write(f"contract-sha256={contract_digest}\n")
        stream.write(f"artifact-name={artifact_name}\n")
        stream.write(f"artifact-prefix={artifact_prefix}\n")
        stream.write(f"staging-value={staging_key}\n")
    print(f"Android NVD artifact generation: {generation}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ImportError, OSError, TypeError, ValueError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

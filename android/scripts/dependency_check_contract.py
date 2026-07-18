from __future__ import annotations

import json
import os
import re
import struct
import tomllib
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

PAYLOAD_TTL_SECONDS = 24 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PRODUCER_CONTRACT_PATHS = (
    ".github/actions/prepare-android/action.yml",
    ".github/actions/restore-android-nvd/action.yml",
    ".github/workflows/android-nvd-cache.yml",
    "android/scripts/certify_dependency_check_nvd_payload.sh",
    "android/scripts/dependency_check_contract.py",
    "android/scripts/dependency_check_nvd_manifest.py",
    "android/scripts/refresh_dependency_check_nvd.sh",
    "android/scripts/verify_dependency_check_report.py",
    "scripts/build_android_nvd_identity.py",
    "scripts/select_android_nvd_artifact.py",
    "scripts/verify_android_nvd_publication_ref.py",
)
_GRADLE_ROOT_AUTHORITY_FILES = frozenset(
    {
        "gradle.properties",
        "gradlew",
        "gradlew.bat",
    }
)
_GRADLE_AUTHORITY_DIRECTORIES = frozenset(
    {
        "build-logic",
        "buildSrc",
        "gradle",
    }
)
_GRADLE_GENERATED_DIRECTORIES = frozenset({".gradle", "build"})
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


def repository_root() -> Path:
    configured = os.environ.get("REPOSITORY_ROOT", "").strip()
    return (
        Path(configured).resolve()
        if configured
        else Path(__file__).resolve().parents[2]
    )


def producer_contract_paths(root: Path) -> tuple[str, ...]:
    paths = set(PRODUCER_CONTRACT_PATHS)
    android_root = root / "android"
    if android_root.is_symlink() or not android_root.is_dir():
        raise ValueError("Android Gradle authority root is missing or unsafe")
    for path in android_root.rglob("*"):
        relative_android = path.relative_to(android_root)
        if any(
            part in _GRADLE_GENERATED_DIRECTORIES
            for part in relative_android.parts
        ):
            continue
        if not path.is_file() and not path.is_symlink():
            continue
        first_part = relative_android.parts[0]
        is_authority = (
            relative_android.as_posix() in _GRADLE_ROOT_AUTHORITY_FILES
            or path.name.endswith((".gradle", ".gradle.kts"))
            or first_part in _GRADLE_AUTHORITY_DIRECTORIES
        )
        if is_authority:
            paths.add(path.relative_to(root).as_posix())
    return tuple(sorted(paths))


def producer_contract_sha256(root: Path) -> str:
    digest = sha256()
    digest.update(b"xpj-android-nvd-producer-contract\0sha256-tree-v1\0")
    for relative in producer_contract_paths(root):
        path = root / Path(relative)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"NVD producer contract file is missing or unsafe: {relative}")
        relative_bytes = relative.encode("utf-8")
        content = path.read_bytes()
        digest.update(struct.pack(">Q", len(relative_bytes)))
        digest.update(relative_bytes)
        digest.update(struct.pack(">Q", len(content)))
        digest.update(content)
    return digest.hexdigest()


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

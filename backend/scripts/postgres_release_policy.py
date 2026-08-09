"""Validated PostgreSQL major-version policy for release and CI consumers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

RELEASE_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "packaging" / "windows-release-config.json"
)
BUILD_TOOLCHAIN_PATH = (
    Path(__file__).resolve().parents[1] / "packaging" / "windows-build-toolchain.json"
)
_VERSION = re.compile(
    r"(?P<major>[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)"
    r"(?:\.(?P<patch>0|[1-9][0-9]*))?"
)
_SERVICE_IMAGE = re.compile(
    r"postgres:(?P<version>[1-9][0-9]*\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?)"
    r"@sha256:[0-9a-f]{64}"
)
_SUPPORTED_WINDOWS_RELEASE_SCHEMAS = frozenset(
    {
        "ticketbox-windows-release-v1",
        "ticketbox-windows-release-v2",
    }
)


@dataclass(frozen=True)
class PostgresReleasePolicy:
    minimum: tuple[int, int, int]
    maximum_exclusive: tuple[int, int, int]
    supported_majors: tuple[int, ...]
    current_major: int
    service_image: str

    def __post_init__(self) -> None:
        if self.supported_majors != (self.current_major,):
            raise ValueError(
                "PostgreSQL CI requires one pinned service image for every supported major"
            )

    def matrix_json(self) -> str:
        return json.dumps(
            {
                "include": [
                    {
                        "postgres-major": str(self.current_major),
                        "postgres-image": self.service_image,
                    }
                ]
            },
            separators=(",", ":"),
        )

    def verify_server_version(
        self,
        raw_version_num: object,
        *,
        expected_major: int,
    ) -> tuple[int, int, int]:
        version = postgres_server_version(raw_version_num)
        if expected_major not in self.supported_majors:
            raise RuntimeError("PostgreSQL matrix major is outside the release policy")
        if version[0] != expected_major:
            raise RuntimeError("PostgreSQL server major does not match its matrix coordinate")
        if not self.minimum <= version < self.maximum_exclusive:
            raise RuntimeError("PostgreSQL server version is outside the release policy")
        return version


def postgres_server_version(raw_version_num: object) -> tuple[int, int, int]:
    if isinstance(raw_version_num, bool):
        raise RuntimeError("invalid PostgreSQL server_version_num")
    if isinstance(raw_version_num, int):
        value = raw_version_num
    elif (
        isinstance(raw_version_num, str)
        and raw_version_num.isascii()
        and raw_version_num.isdecimal()
    ):
        value = int(raw_version_num)
    else:
        raise RuntimeError("invalid PostgreSQL server_version_num")
    major, remainder = divmod(value, 10_000)
    if major < 1:
        raise RuntimeError("invalid PostgreSQL server_version_num")
    if major >= 10:
        return major, remainder, 0
    minor, patch = divmod(remainder, 100)
    return major, minor, patch


def _version(raw: object, field: str) -> tuple[int, int, int]:
    if not isinstance(raw, str) or (match := _VERSION.fullmatch(raw)) is None:
        raise RuntimeError(f"invalid PostgreSQL release version policy: {field}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )


def _pinned_postgres_source(path: Path) -> tuple[tuple[int, int, int], str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        source = raw["installer_vendor_sources"]["postgresql"]
        version = source["version"]
        service_image = source["ci_service_image"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("pinned PostgreSQL build-toolchain version is missing") from exc
    if not isinstance(version, str):
        raise RuntimeError("pinned PostgreSQL build-toolchain version is invalid")
    upstream, separator, build = version.partition("-")
    if separator and (not build.isascii() or not build.isdecimal() or int(build) < 1):
        raise RuntimeError("pinned PostgreSQL build-toolchain revision is invalid")
    pinned_version = _version(upstream, "pinned runtime")
    if (
        not isinstance(service_image, str)
        or (image_match := _SERVICE_IMAGE.fullmatch(service_image)) is None
        or _version(image_match.group("version"), "CI service image") != pinned_version
    ):
        raise RuntimeError("pinned PostgreSQL CI service image is invalid")
    return pinned_version, service_image


def load_postgres_release_policy(
    path: Path = RELEASE_CONFIG_PATH,
    toolchain_path: Path = BUILD_TOOLCHAIN_PATH,
) -> PostgresReleasePolicy:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(raw, dict)
        or raw.get("schema") not in _SUPPORTED_WINDOWS_RELEASE_SCHEMAS
    ):
        raise RuntimeError("unsupported Windows release config schema")
    policy = raw.get("postgres_version_policy")
    if not isinstance(policy, dict) or set(policy) != {"minimum", "maximum_exclusive"}:
        raise RuntimeError("invalid PostgreSQL release version policy fields")
    minimum = _version(policy["minimum"], "minimum")
    maximum = _version(policy["maximum_exclusive"], "maximum_exclusive")
    if maximum[1:] != (0, 0) or minimum >= maximum:
        raise RuntimeError("PostgreSQL maximum_exclusive must be a later major boundary")
    majors = tuple(range(minimum[0], maximum[0]))
    if not majors:
        raise RuntimeError("PostgreSQL release policy supports no major versions")
    pinned_runtime, service_image = _pinned_postgres_source(toolchain_path)
    if not minimum <= pinned_runtime < maximum:
        raise RuntimeError("pinned PostgreSQL runtime is outside the release policy")
    if majors != (pinned_runtime[0],):
        raise RuntimeError(
            "PostgreSQL release policy spans majors without one pinned CI image per major"
        )
    return PostgresReleasePolicy(
        minimum=minimum,
        maximum_exclusive=maximum,
        supported_majors=majors,
        current_major=pinned_runtime[0],
        service_image=service_image,
    )


POSTGRES_RELEASE_POLICY = load_postgres_release_policy()

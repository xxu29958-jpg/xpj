"""Managed Windows release-version grammar for runtime and build evidence."""

from __future__ import annotations

import re

_MANAGED_RELEASE_VERSION_PATTERN = re.compile(
    r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:\.([0-9]+))?\Z",
)
_WINDOWS_VERSION_COMPONENT_MAX = 65_535


def is_managed_release_version(value: object) -> bool:
    """Match the installer downgrade and Windows file-version contract."""
    if not isinstance(value, str):
        return False
    match = _MANAGED_RELEASE_VERSION_PATTERN.fullmatch(value)
    return match is not None and all(
        int(component) <= _WINDOWS_VERSION_COMPONENT_MAX
        for component in match.groups(default="0")
    )

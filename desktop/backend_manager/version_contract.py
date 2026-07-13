"""Managed Windows release-version grammar for runtime and build evidence."""

from __future__ import annotations

import re

_MANAGED_RELEASE_VERSION_PATTERN = re.compile(
    r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:\.([0-9]+))?\Z",
)
_WINDOWS_VERSION_COMPONENT_MAX = 65_535
_WINDOWS_VERSION_COMPONENT_MAX_TEXT = str(_WINDOWS_VERSION_COMPONENT_MAX)


def _component_is_supported(component: str) -> bool:
    normalized = component.lstrip("0") or "0"
    return len(normalized) < len(_WINDOWS_VERSION_COMPONENT_MAX_TEXT) or (
        len(normalized) == len(_WINDOWS_VERSION_COMPONENT_MAX_TEXT)
        and normalized <= _WINDOWS_VERSION_COMPONENT_MAX_TEXT
    )


def is_managed_release_version(value: object) -> bool:
    """Match the installer downgrade and Windows file-version contract."""
    if not isinstance(value, str):
        return False
    match = _MANAGED_RELEASE_VERSION_PATTERN.fullmatch(value)
    return match is not None and all(
        _component_is_supported(component) for component in match.groups(default="0")
    )

"""Select the CI provider whose workflow contract is authoritative for this run."""

from __future__ import annotations

import os
import pathlib
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

CI_AUDIT_PROVIDER_ENV = "XPJ_CI_AUDIT_PROVIDER"
PLATFORM_WORKFLOW_PARTS = {"GitHub": ".github", "Gitea": ".gitea"}
_PROVIDER_NAMES = {name.casefold(): name for name in PLATFORM_WORKFLOW_PARTS}
_TRUE_VALUES = {"1", "true"}


def _is_true(source: Mapping[str, str], name: str) -> bool:
    return source.get(name, "").strip().casefold() in _TRUE_VALUES


def _runtime_ci_platform(source: Mapping[str, str]) -> str | None:
    """Identify the runner from provider-owned, non-overridable runtime state."""
    gitea_actions = _is_true(source, "GITEA_ACTIONS")
    github_actions = _is_true(source, "GITHUB_ACTIONS")
    if not gitea_actions and not github_actions:
        if _is_true(source, "CI"):
            raise ValueError("unsupported CI runtime; expected GitHub Actions or Gitea Actions")
        return None

    server_url = source.get("GITHUB_SERVER_URL", "").strip()
    server_host = (urlsplit(server_url).hostname or "").casefold()
    if not server_host:
        raise ValueError("CI runtime did not provide a valid GITHUB_SERVER_URL")
    if gitea_actions:
        if not github_actions or server_host == "github.com":
            raise ValueError("conflicting GitHub/Gitea runtime identity")
        return "Gitea"
    if server_host != "github.com":
        raise ValueError(f"unsupported GitHub Actions server: {server_host!r}")
    return "GitHub"


def selected_ci_platforms(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return one provider in CI, or both for the local aggregate audit."""
    source = os.environ if environment is None else environment
    raw_value = source.get(CI_AUDIT_PROVIDER_ENV)
    raw = "all" if raw_value is None else raw_value.strip().casefold()
    runtime_platform = _runtime_ci_platform(source)
    if runtime_platform is not None:
        expected = runtime_platform.casefold()
        if raw_value is None:
            raise ValueError(f"{CI_AUDIT_PROVIDER_ENV} is required in CI")
        if raw != expected:
            raise ValueError(
                f"{CI_AUDIT_PROVIDER_ENV}={raw!r} does not match {runtime_platform} runtime"
            )
        return (runtime_platform,)
    if raw in {"", "all"}:
        return tuple(PLATFORM_WORKFLOW_PARTS)
    platform = _PROVIDER_NAMES.get(raw)
    if platform is None:
        supported = ", ".join((*_PROVIDER_NAMES, "all"))
        raise ValueError(
            f"{CI_AUDIT_PROVIDER_ENV} must be one of {supported}; got {raw!r}"
        )
    return (platform,)


def workflow_dirs_for_platforms(
    workflow_dirs: Sequence[pathlib.Path],
    platforms: Sequence[str],
) -> list[pathlib.Path]:
    parts = {PLATFORM_WORKFLOW_PARTS[platform] for platform in platforms}
    return [path for path in workflow_dirs if any(part in path.parts for part in parts)]

"""Loader for the standalone CI-gap audit module used by contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "_audit_ci_gap.py"


def load_ci_gap_audit() -> object:
    old_path = list(sys.path)
    module_dir = str(_MODULE_PATH.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    try:
        spec = importlib.util.spec_from_file_location("_audit_ci_gap", _MODULE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = old_path


def assert_ci_provider_selection_contract(mod: object) -> None:
    assert mod.selected_ci_platforms({}) == ("GitHub", "Gitea")
    assert mod.selected_ci_platforms({"XPJ_CI_AUDIT_PROVIDER": "github"}) == (
        "GitHub",
    )
    github_runtime = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://github.com",
        "XPJ_CI_AUDIT_PROVIDER": "github",
    }
    assert mod.selected_ci_platforms(github_runtime) == ("GitHub",)
    with pytest.raises(ValueError, match="does not match GitHub runtime"):
        mod.selected_ci_platforms(
            {**github_runtime, "XPJ_CI_AUDIT_PROVIDER": "gitea"}
        )

    gitea_runtime = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "GITEA_ACTIONS": "true",
        "GITHUB_SERVER_URL": "https://git.example.test",
        "XPJ_CI_AUDIT_PROVIDER": "gitea",
    }
    assert mod.selected_ci_platforms(gitea_runtime) == ("Gitea",)
    with pytest.raises(ValueError, match="does not match Gitea runtime"):
        mod.selected_ci_platforms(
            {**gitea_runtime, "XPJ_CI_AUDIT_PROVIDER": "github"}
        )
    with pytest.raises(ValueError, match="conflicting GitHub/Gitea"):
        mod.selected_ci_platforms(
            {**gitea_runtime, "GITHUB_SERVER_URL": "https://github.com"}
        )
    with pytest.raises(ValueError, match="required in CI"):
        mod.selected_ci_platforms(
            {
                key: value
                for key, value in github_runtime.items()
                if key != "XPJ_CI_AUDIT_PROVIDER"
            }
        )

"""Loader for the standalone CI-gap audit module used by contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
TEST_IMPACT_SOURCE_PREFIXES = ("backend/scripts/",)


def load_ci_gap_module(module_name: str) -> object:
    module_path = _SCRIPTS_DIR / f"{module_name}.py"
    old_path = list(sys.path)
    module_dir = str(_SCRIPTS_DIR)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = old_path


def load_ci_gap_audit() -> object:
    return load_ci_gap_module("_audit_ci_gap")

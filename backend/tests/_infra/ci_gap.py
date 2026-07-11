"""Loader for the standalone CI-gap audit module used by contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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

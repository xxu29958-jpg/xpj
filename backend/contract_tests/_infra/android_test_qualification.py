"""Load the Android qualification script as a testable Python module."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPOSITORY_ROOT / "android" / "scripts" / "verify_android_test_qualification.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_test_android_test_qualification",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualification = _load_script()

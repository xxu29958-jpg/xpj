"""Existing browser discovery and Desktop CDP transport for actual Web consumers."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


_EDGE_CDP: ModuleType | None = None


def _discover_edge() -> str:
    if sys.platform != "win32":
        pytest.skip("real Web consumer gate requires Windows Microsoft Edge")

    candidates = [shutil.which("msedge")]
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidates.append(str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    pytest.skip("real Web consumer gate requires Microsoft Edge")


def _discover_database_browser() -> str:
    """Run database-backed Web journeys in the existing PostgreSQL lane."""
    if sys.platform == "win32":
        return _discover_edge()
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    if os.environ.get("CI"):
        pytest.fail("PostgreSQL Web journeys require an installed Chromium browser")
    pytest.skip("PostgreSQL Web journeys require an installed Chromium browser")


def _edge_cdp() -> ModuleType:
    """Reuse only Desktop's dependency-free Edge transport, not its product fixture."""
    global _EDGE_CDP
    if _EDGE_CDP is not None:
        return _EDGE_CDP
    module_path = _REPO_ROOT / "desktop" / "tests" / "_edge_cdp.py"
    spec = importlib.util.spec_from_file_location("_ticketbox_shared_edge_cdp", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _EDGE_CDP = module
    return module

"""Regression test for the stale-allowlist early-return bug.

PR #85 originally returned 0 from ``_audit_service_graph.main`` as
soon as no cycles were detected, which bypassed the stale-allowlist
fail path entirely — KNOWN_CYCLES could silently rot once its cycle
was fixed. Codex flagged this twice before it actually got patched;
this test makes the regression loud.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load() -> object:
    """Reload so monkey-patched KNOWN_CYCLES from a previous test doesn't leak."""
    return importlib.reload(importlib.import_module("_audit_service_graph"))


def test_no_cycles_no_stale_returns_zero(monkeypatch):
    """Empty allowlist + clean graph → PASS."""
    mod = _load()
    monkeypatch.setattr(mod, "KNOWN_CYCLES", set())
    assert mod.main() == 0


def test_stale_allowlist_entry_fails_even_when_graph_is_clean(monkeypatch):
    """A KNOWN_CYCLES entry whose cycle is no longer in the codebase
    must fail the audit. Without this, fixing a cycle but forgetting
    to clean the allowlist would leave a silent landmine for the next
    refactor."""
    mod = _load()
    fake = frozenset({"app.services.fake_a", "app.services.fake_b"})
    monkeypatch.setattr(mod, "KNOWN_CYCLES", {fake})
    assert mod.main() == 1

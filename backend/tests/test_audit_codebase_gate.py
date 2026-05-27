"""Regression tests for the codebase audit hard gate."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load() -> object:
    return importlib.reload(importlib.import_module("_audit_codebase"))


def _load_gate() -> object:
    return importlib.reload(importlib.import_module("codebase_audit_gate"))


def test_codebase_known_debt_baseline_returns_zero() -> None:
    gate = _load_gate()
    assert gate.evaluate_debt(dict(gate.CODEBASE_DEBT_LIMITS)) == 0


def test_codebase_debt_regression_returns_one() -> None:
    gate = _load_gate()
    counts = dict(gate.CODEBASE_DEBT_LIMITS)
    counts["long_functions"] += 1
    assert gate.evaluate_debt(counts) == 1


def test_codebase_main_propagates_audit_regression(monkeypatch) -> None:
    mod = _load()
    gate = _load_gate()

    def fake_audit() -> dict[str, int]:
        counts = dict(gate.CODEBASE_DEBT_LIMITS)
        counts["long_functions"] += 1
        return counts

    monkeypatch.setattr(mod, "AUDITS", (fake_audit,))
    assert mod.main() == 1

"""Audit binding for the native Web manual-expense create topology hop."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_pr_delta_accepts_exact_web_manual_expense_create_hop(monkeypatch) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    baseline = dict(mod.STRICT_EQUALITY_BASELINE)
    baseline["mutate_token_exempted"] = 130
    monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)

    _bootstrapped, violations, _removed = mod._compute_ratchet_findings(
        {"mutate_token_exempted": 129},
        base_commit="90ed5b50e18bf18d687e0da6eb28aaab015e7c40",
    )

    assert violations == []

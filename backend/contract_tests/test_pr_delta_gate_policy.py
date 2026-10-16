from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_pr_delta_uses_test_counts_as_floors_but_keeps_topology_exact(
    monkeypatch,
) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    baseline = {
        "backend_pytest_count": 2403,
        "mutate_token_carriers": 95,
    }
    monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)
    monkeypatch.setattr(mod, "_read_base_strict_baseline", lambda: (True, baseline))

    assert mod.evaluate_pr_delta_metrics(
        {"backend_pytest_count": 2404, "mutate_token_carriers": 95}
    ) == 0
    assert mod.evaluate_pr_delta_metrics(
        {"backend_pytest_count": 2402, "mutate_token_carriers": 95}
    ) == 1
    assert mod.evaluate_pr_delta_metrics(
        {"backend_pytest_count": 2404, "mutate_token_carriers": 96}
    ) == 1

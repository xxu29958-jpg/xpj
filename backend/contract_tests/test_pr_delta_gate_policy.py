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
        "installer_pytest_count": 76,
        "mutate_token_carriers": 95,
    }
    monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)
    previous = {**baseline, "backend_pytest_count": 2404, "installer_pytest_count": 77}
    monkeypatch.setattr(mod, "_read_base_strict_baseline", lambda: (True, previous))

    # A reviewed reduction changes the checked-in floor; actual collection must
    # still meet it. Missing evidence and OCC topology retain their own gates.
    assert mod.evaluate_pr_delta_metrics(baseline) == 0
    assert mod.evaluate_pr_delta_metrics(previous) == 0
    for key in ("backend_pytest_count", "installer_pytest_count"):
        assert mod.evaluate_pr_delta_metrics({**baseline, key: baseline[key] - 1}) == 1
    assert mod.evaluate_pr_delta_metrics(
        {**baseline, "mutate_token_carriers": 96}
    ) == 1

"""One-shot, exact-base test-retirement ratchets for completed owner cuts."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_pr_delta_allows_only_exact_installer_test_retirements(monkeypatch) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    retirement_base = "051464999fc1f71d9072bb5c9cfc012b521181cd"

    def violations_for(
        key: str,
        base: int,
        current: int,
        *,
        base_commit: str = retirement_base,
    ) -> list[str]:
        baseline = dict(mod.STRICT_EQUALITY_BASELINE)
        baseline[key] = current
        monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)
        return mod._compute_ratchet_findings(
            {key: base},
            base_commit=base_commit,
        )[1]

    assert violations_for("installer_pytest_count", 387, 379) == []
    neighboring_installer_hops = (
        (386, 379),
        (387, 380),
        (387, 378),
        (388, 379),
        (379, 378),
    )
    for base_count, current_count in neighboring_installer_hops:
        assert len(violations_for("installer_pytest_count", base_count, current_count)) == 1
    assert len(
        violations_for(
            "installer_pytest_count",
            387,
            379,
            base_commit="f" * 40,
        )
    ) == 1

    generation_base = "9d74b04f318362d5e222d897787db074bb5ca8ab"
    assert violations_for(
        "installer_pytest_count",
        379,
        282,
        base_commit=generation_base,
    ) == []
    neighboring_generation_hops = (
        (378, 282),
        (379, 283),
        (379, 281),
        (380, 282),
        (282, 281),
    )
    for base_count, current_count in neighboring_generation_hops:
        assert len(
            violations_for(
                "installer_pytest_count",
                base_count,
                current_count,
                base_commit=generation_base,
            )
        ) == 1
    assert len(
        violations_for(
            "installer_pytest_count",
            379,
            282,
            base_commit="f" * 40,
        )
    ) == 1

    for base_count, current_count in ((379, 282), (387, 379)):
        violations = violations_for(
            "mutate_token_carriers",
            base_count,
            current_count,
            base_commit=generation_base if base_count == 379 else retirement_base,
        )
        assert len(violations) == 1
        assert "mutate_token_carriers" in violations[0]
        assert f"base={base_count}, current={current_count}" in violations[0]

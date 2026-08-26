"""One-shot, exact-base test-retirement ratchets for completed owner cuts."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _violations_for(
    mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    base: int,
    current: int,
    base_commit: str,
) -> list[str]:
    baseline = dict(mod.STRICT_EQUALITY_BASELINE)
    baseline[key] = current
    monkeypatch.setattr(mod, "STRICT_EQUALITY_BASELINE", baseline)
    return mod._compute_ratchet_findings(
        {key: base},
        base_commit=base_commit,
    )[1]


def _assert_exact_installer_hop(
    mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_commit: str,
    accepted_hop: tuple[int, int],
    neighboring_hops: tuple[tuple[int, int], ...],
) -> None:
    base_count, current_count = accepted_hop
    assert (
        _violations_for(
            mod,
            monkeypatch,
            "installer_pytest_count",
            base_count,
            current_count,
            base_commit,
        )
        == []
    )
    for adjacent_base, adjacent_current in neighboring_hops:
        assert (
            len(
                _violations_for(
                    mod,
                    monkeypatch,
                    "installer_pytest_count",
                    adjacent_base,
                    adjacent_current,
                    base_commit,
                )
            )
            == 1
        )
    assert (
        len(
            _violations_for(
                mod,
                monkeypatch,
                "installer_pytest_count",
                base_count,
                current_count,
                "f" * 40,
            )
        )
        == 1
    )


def test_pr_delta_allows_only_exact_installer_test_retirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    hops = (
        (
            "051464999fc1f71d9072bb5c9cfc012b521181cd",
            (387, 379),
            ((386, 379), (387, 380), (387, 378), (388, 379), (379, 378)),
        ),
        (
            "9d74b04f318362d5e222d897787db074bb5ca8ab",
            (379, 282),
            ((378, 282), (379, 283), (379, 281), (380, 282), (282, 281)),
        ),
        (
            "ce9a5aa413f20e5455fe0572d9416187038135b0",
            (283, 260),
            ((282, 260), (283, 261), (283, 259), (284, 260), (260, 259)),
        ),
        (
            "6557125826d7c76a06568164814b4e5cb9e08f88",
            (369, 76),
            ((368, 76), (369, 77), (369, 75), (370, 76), (76, 75)),
        ),
    )
    for base_commit, accepted_hop, neighboring_hops in hops:
        _assert_exact_installer_hop(
            mod,
            monkeypatch,
            base_commit=base_commit,
            accepted_hop=accepted_hop,
            neighboring_hops=neighboring_hops,
        )
    for base_count, current_count in ((369, 76), (283, 260), (379, 282), (387, 379)):
        base_commit = next(commit for commit, hop, _ in hops if hop == (base_count, current_count))
        violations = _violations_for(
            mod,
            monkeypatch,
            "mutate_token_carriers",
            base_count,
            current_count,
            base_commit,
        )
        assert len(violations) == 1
        assert "mutate_token_carriers" in violations[0]
        assert f"base={base_count}, current={current_count}" in violations[0]

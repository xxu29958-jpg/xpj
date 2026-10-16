"""Exact-base OCC retirement boundaries for completed owner cuts."""

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


def test_owner_recycle_route_retirement_allows_only_its_exact_count_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    base_commit = "5436e40dddf437614ec01bf5703a5d5ce8197be3"
    assert _violations_for(mod, monkeypatch, "mutate_token_carriers", 106, 105, base_commit) == []
    for before, after, source in ((106, 104, base_commit), (107, 105, base_commit), (105, 104, base_commit), (106, 105, "f" * 40)):
        assert len(_violations_for(mod, monkeypatch, "mutate_token_carriers", before, after, source)) == 1


def test_saved_view_create_admission_does_not_exempt_additional_writers(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    base_commit = "8e5529e49434c7d0650172cf7fc40668446627e2"
    assert _violations_for(mod, monkeypatch, "mutate_token_exempted", 128, 129, base_commit) == []
    for before, after, source in ((128, 130, base_commit), (129, 130, base_commit), (128, 129, "f" * 40)):
        assert len(_violations_for(mod, monkeypatch, "mutate_token_exempted", before, after, source)) == 1


def test_original_task_admission_does_not_waive_unrelated_occ_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    base_commit = "0e4932d933bec3d2d5618d736d61359360cd7884"
    assert _violations_for(mod, monkeypatch, "mutate_token_exempted", 128, 130, base_commit) == []
    for before, after, source in ((128, 131, base_commit), (129, 131, base_commit), (128, 130, "f" * 40)):
        assert len(_violations_for(mod, monkeypatch, "mutate_token_exempted", before, after, source)) == 1
    assert len(_violations_for(mod, monkeypatch, "mutate_token_carriers", 138, 137, base_commit)) == 1


def test_owner_tag_route_retirement_does_not_waive_other_occ_losses(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = importlib.reload(importlib.import_module("codebase_audit_gate"))
    base_commit = "45ebec82a701f94107cd2d63b4749548298e3433"
    assert _violations_for(mod, monkeypatch, "mutate_token_carriers", 136, 135, base_commit) == []
    for before, after, source in ((136, 134, base_commit), (137, 135, base_commit),
                                  (135, 134, base_commit), (136, 135, "f" * 40)):
        assert len(_violations_for(mod, monkeypatch, "mutate_token_carriers", before, after, source)) == 1

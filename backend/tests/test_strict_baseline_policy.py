from __future__ import annotations

import importlib
import subprocess

import pytest

from scripts.strict_baseline_policy import parse_strict_baseline_policy

pytestmark = pytest.mark.parallel_safe


def test_base_ratchet_policy_is_parsed_without_executing_imports() -> None:
    policy = parse_strict_baseline_policy(
        "\n".join(
            (
                "from missing_dependency import never_execute",
                "STRICT_EQUALITY_BASELINE = {'tests': 3}",
                "BASELINE_RATCHET_UP = frozenset({'tests'})",
                "BASELINE_RATCHET_DOWN = frozenset()",
            )
        )
    )

    assert policy.baseline == {"tests": 3}
    assert policy.ratchet_up == {"tests"}
    assert policy.ratchet_policy_present


def test_unreadable_base_returns_a_typed_fail_closed_policy(monkeypatch) -> None:
    gate = importlib.reload(importlib.import_module("scripts.codebase_audit_gate"))
    monkeypatch.setattr(gate, "_strict_baseline_git_ref", lambda: "missing-base")

    def fail_to_read_base(*_args: object, **_kwargs: object) -> str:
        raise subprocess.CalledProcessError(1, ["git", "show"])

    monkeypatch.setattr(gate.subprocess, "check_output", fail_to_read_base)

    readable, policy = gate._read_base_strict_policy()

    assert not readable
    assert isinstance(policy, gate._StrictBaselinePolicy)
    assert not policy.ratchet_policy_present


@pytest.mark.parametrize(
    "mutation",
    (
        "BASELINE_RATCHET_UP |= {'tests_extra'}",
        "if True:\n    BASELINE_RATCHET_UP = frozenset({'tests_extra'})",
        "STRICT_EQUALITY_BASELINE.update({'tests': 4})",
        "STRICT_EQUALITY_BASELINE['tests'] = 4",
        "del STRICT_EQUALITY_BASELINE['tests']",
        "alias = STRICT_EQUALITY_BASELINE\nalias.update({'tests': 4})",
    ),
)
def test_literal_policy_rejects_noncanonical_protected_writes(mutation: str) -> None:
    content = "\n".join(
        (
            "STRICT_EQUALITY_BASELINE = {'tests': 3, 'tests_extra': 4}",
            "BASELINE_RATCHET_UP = frozenset({'tests'})",
            "BASELINE_RATCHET_DOWN = frozenset()",
            mutation,
        )
    )

    with pytest.raises(ValueError, match="protected|alias"):
        parse_strict_baseline_policy(content)


def test_ratchet_policy_rejects_unknown_memberships(monkeypatch) -> None:
    gate = importlib.reload(importlib.import_module("scripts.codebase_audit_gate"))
    monkeypatch.setattr(
        gate,
        "STRICT_EQUALITY_BASELINE",
        {"mutate_token_exempted": 123},
    )
    monkeypatch.setattr(gate, "BASELINE_RATCHET_UP", frozenset())
    monkeypatch.setattr(
        gate,
        "BASELINE_RATCHET_DOWN",
        frozenset({"mutate_token_exemption"}),
    )
    violations = gate._compute_ratchet_policy_findings()

    assert any("unknown counter" in violation for violation in violations)


def test_ratchet_policy_rejects_malformed_current_source(monkeypatch) -> None:
    gate = importlib.reload(importlib.import_module("scripts.codebase_audit_gate"))
    monkeypatch.setattr(
        gate,
        "_parse_base_strict_policy",
        lambda _content: (_ for _ in ()).throw(ValueError("mutated source")),
    )

    violations = gate._compute_ratchet_policy_findings()

    assert "current gate source policy is malformed: mutated source" in violations

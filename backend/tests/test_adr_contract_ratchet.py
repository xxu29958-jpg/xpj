from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from adr_contract_ratchet import (  # noqa: E402
    _calibration_commit_errors,
    accepted_history_ratchet_errors,
    audit_base_ratchets,
    bootstrap_legacy_errors,
    legacy_ratchet_errors,
)
from adr_contract_registry import build_registry  # noqa: E402
from adr_contract_test_support import (  # noqa: E402
    baseline_payload,
    calibration_payload,
    legacy_entry,
    valid_adr,
    write_baseline,
    write_v2,
)
from adr_contract_views import registry_json  # noqa: E402


def test_coordinated_legacy_rewrite_cannot_resign_baseline(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 original history\n", encoding="utf-8")
    base_row = legacy_entry(legacy, "0001")
    base = baseline_payload([base_row])

    legacy.write_text("# 0001 rewritten history\n", encoding="utf-8")
    current_row = legacy_entry(legacy, "0001")
    baseline = write_baseline(tmp_path, [current_row])
    assert build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)

    assert legacy_ratchet_errors(
        base,
        baseline_payload([current_row]),
        calibration_payload([base_row]),
        calibration_payload([current_row]),
    ) == ["ADR-0001 retained legacy baseline row changed"]


def test_legacy_status_can_be_recalibrated_without_resigning_history(
    tmp_path: Path,
) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 original history\n", encoding="utf-8")
    base_row = legacy_entry(legacy, "0001")
    baseline = write_baseline(tmp_path, [base_row])
    current_row = dict(base_row)
    current_row.update(
        implementation_status="nonconformant",
        confidence="high",
        reviewed_against_commit="2" * 40,
        reason="Runtime inspection found a contract violation",
    )
    calibration = calibration_payload([current_row])
    baseline.with_name("legacy-calibration.json").write_text(
        json.dumps(calibration, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    registry = build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)

    assert registry.entries[0].implementation_status == "nonconformant"
    assert registry.entries[0].reviewed_against_commit == "2" * 40
    assert registry.entries[0].calibration_reason == ("Runtime inspection found a contract violation")
    rendered = json.loads(registry_json(registry))["entries"][0]
    assert rendered["reviewed_against_commit"] == "2" * 40
    assert rendered["calibration_reason"] == ("Runtime inspection found a contract violation")
    assert (
        legacy_ratchet_errors(
            baseline_payload([base_row]),
            baseline_payload([base_row]),
            calibration_payload([base_row]),
            calibration,
        )
        == []
    )


def test_legacy_recalibration_requires_a_fresh_reason(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 original history\n", encoding="utf-8")
    base_row = legacy_entry(legacy, "0001")
    baseline = write_baseline(tmp_path, [base_row])
    current_row = dict(base_row)
    current_row["implementation_status"] = "nonconformant"
    calibration = calibration_payload([current_row])
    baseline.with_name("legacy-calibration.json").write_text(
        json.dumps(calibration, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)

    assert legacy_ratchet_errors(
        baseline_payload([base_row]),
        baseline_payload([base_row]),
        calibration_payload([base_row]),
        calibration,
    ) == [
        "ADR-0001 calibration changed without an updated review reason",
        "ADR-0001 calibration changed without a new review commit",
    ]


def test_legacy_recalibration_cannot_revive_rejected_or_move_date_backwards(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "0001-legacy.md"
    legacy.write_text("# 0001 legacy\n", encoding="utf-8")
    base_row = {
        **legacy_entry(legacy, "0001"),
        "decision_status": "rejected",
    }
    current_row = {
        **base_row,
        "decision_status": "accepted",
        "reviewed_at": "2026-07-10",
        "reviewed_against_commit": "2" * 40,
        "reason": "Attempted reactivation",
    }

    errors = legacy_ratchet_errors(
        baseline_payload([base_row]),
        baseline_payload([base_row]),
        calibration_payload([base_row]),
        calibration_payload([current_row]),
    )

    assert errors == [
        "ADR-0001 decision status cannot transition from rejected to accepted",
        "ADR-0001 calibration reviewed_at moved backwards",
    ]


def test_legacy_history_cannot_be_removed_or_rewritten_as_same_id_v2(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 original history\n", encoding="utf-8")
    base_row = legacy_entry(legacy, "0001")
    base = baseline_payload([base_row])
    base_calibration = calibration_payload([base_row])
    legacy.unlink()
    baseline = write_baseline(tmp_path)
    assert build_registry(
        decisions_dir=decisions,
        legacy_baseline_path=baseline,
    )

    assert legacy_ratchet_errors(
        base,
        baseline_payload(),
        base_calibration,
        calibration_payload(),
    ) == ["legacy baseline removed frozen rows; use a new successor ADR: 0001"]

    migrated = write_v2(tmp_path, "0001")
    assert build_registry(
        decisions_dir=migrated.parent,
        legacy_baseline_path=baseline,
    )
    assert (
        legacy_ratchet_errors(
            base,
            baseline_payload(),
            base_calibration,
            calibration_payload(),
        )
        == ["legacy baseline removed frozen rows; use a new successor ADR: 0001"]
    )


def test_legacy_baseline_cannot_add_even_old_number(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 late debt\n", encoding="utf-8")
    current_row = legacy_entry(legacy, "0001")
    baseline = write_baseline(tmp_path, [current_row])
    assert build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)

    assert legacy_ratchet_errors(
        baseline_payload(),
        baseline_payload([current_row]),
        calibration_payload(),
        calibration_payload([current_row]),
    ) == [
        "legacy baseline added frozen rows: 0001",
        "legacy calibration added rows outside the frozen baseline: 0001",
    ]


def test_bootstrap_baseline_must_match_base_file_identity(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 current\n", encoding="utf-8")
    row = legacy_entry(legacy, "0001")
    current = baseline_payload([row])

    errors = bootstrap_legacy_errors(
        current,
        base_commit="1" * 40,
        committed_legacy_files={
            "0001": ("docs/DECISIONS/0001-legacy.md", "f" * 64),
        },
    )

    assert errors == ["ADR-0001 bootstrap row does not match base file identity"]


def test_bootstrap_baseline_cannot_bind_to_a_branch_internal_snapshot() -> None:
    current = baseline_payload(bootstrap_base_commit="2" * 40)

    errors = bootstrap_legacy_errors(
        current,
        base_commit="1" * 40,
        committed_legacy_files={},
    )

    assert errors == [
        "legacy baseline bootstrap_base_commit does not equal resolved PR base"
    ]


def test_accepted_history_fingerprint_rejects_rewrite(tmp_path: Path) -> None:
    adr = write_v2(tmp_path, "0065")
    baseline = write_baseline(tmp_path)
    base_registry = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    base_payload = json.loads(registry_json(base_registry))

    adr.write_text(
        valid_adr().replace(
            "Generate every derived view from the authoritative source.",
            "Rewrite accepted history in place.",
        ),
        encoding="utf-8",
    )
    rewritten = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    assert accepted_history_ratchet_errors(base_payload, rewritten) == [
        "ADR-0065 frozen accepted history changed; write an amendment/superseding ADR"
    ]


def test_accepted_history_allows_only_operational_metadata_update(
    tmp_path: Path,
) -> None:
    adr = write_v2(tmp_path, "0065")
    baseline = write_baseline(tmp_path)
    base_registry = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    base_payload = json.loads(registry_json(base_registry))

    updated = valid_adr(
        implementation_status="partial",
        verification_status="stale",
    )
    updated = updated.replace('decision_owner = "decision owner"', 'decision_owner = "new owner"')
    adr.write_text(updated, encoding="utf-8")
    current = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    assert accepted_history_ratchet_errors(base_payload, current) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("contract-fixture/0065/v1", "contract-fixture/0065/rebound"),
        (
            "- `python backend/scripts/_audit_adr_contracts.py`",
            "- claim a verification run that never happened",
        ),
        ('summary = "Deterministic fixture"', 'summary = "Rebound decision meaning"'),
        (
            'current_scope = "Test-only contract scope"',
            'current_scope = "Expanded semantic scope"',
        ),
    ],
)
def test_accepted_history_freezes_semantic_metadata_and_complete_body(
    tmp_path: Path, old: str, new: str
) -> None:
    adr = write_v2(tmp_path, "0065")
    baseline = write_baseline(tmp_path)
    base = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    base_payload = json.loads(registry_json(base))
    adr.write_text(valid_adr().replace(old, new), encoding="utf-8")

    current = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    assert accepted_history_ratchet_errors(base_payload, current) == [
        "ADR-0065 frozen accepted history changed; write an amendment/superseding ADR"
    ]


def test_accepted_history_freezes_relations(tmp_path: Path) -> None:
    adr = write_v2(tmp_path, "0065")
    write_v2(tmp_path, "0066")
    baseline = write_baseline(tmp_path)
    base = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    base_payload = json.loads(registry_json(base))
    adr.write_text(
        valid_adr(relations=(("depends-on", "0066", "semantic dependency"),)),
        encoding="utf-8",
    )
    current = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    assert accepted_history_ratchet_errors(base_payload, current) == [
        "ADR-0065 frozen accepted history changed; write an amendment/superseding ADR"
    ]


def test_accepted_history_cannot_disappear(tmp_path: Path) -> None:
    adr = write_v2(tmp_path, "0065")
    baseline = write_baseline(tmp_path)
    base_registry = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    base_payload = json.loads(registry_json(base_registry))
    adr.unlink()
    current = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    assert accepted_history_ratchet_errors(base_payload, current) == [
        "accepted ADR-0065 disappeared or reverted from schema v2"
    ]


def test_proposed_history_can_change_before_acceptance(tmp_path: Path) -> None:
    adr = write_v2(tmp_path, "0065", decision_status="proposed")
    baseline = write_baseline(tmp_path)
    proposed = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    base_payload = json.loads(registry_json(proposed))
    adr.write_text(
        valid_adr().replace(
            "Generate every derived view from the authoritative source.",
            "Accept the refined proposal.",
        ),
        encoding="utf-8",
    )
    accepted = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    assert accepted_history_ratchet_errors(base_payload, accepted) == []


def test_superseded_history_remains_frozen_and_cannot_be_reactivated(
    tmp_path: Path,
) -> None:
    adr = write_v2(
        tmp_path,
        "0065",
        decision_status="superseded",
        verification_status="stale",
    )
    baseline = write_baseline(tmp_path)
    superseded = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    base_payload = json.loads(registry_json(superseded))
    adr.write_text(
        valid_adr().replace(
            "Generate every derived view from the authoritative source.",
            "Reactivate and rewrite the superseded decision.",
        ),
        encoding="utf-8",
    )
    current = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    assert accepted_history_ratchet_errors(base_payload, current) == [
        "ADR-0065 decision status cannot transition from superseded to accepted",
        "ADR-0065 frozen accepted history changed; write an amendment/superseding ADR",
    ]


def test_rejected_history_remains_frozen_and_cannot_be_reactivated(tmp_path: Path) -> None:
    adr = write_v2(
        tmp_path,
        "0065",
        decision_status="rejected",
        implementation_status="not-started",
        verification_status="stale",
    )
    baseline = write_baseline(tmp_path)
    rejected = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    base_payload = json.loads(registry_json(rejected))
    reactivated = valid_adr().replace(
        "Generate every derived view from the authoritative source.",
        "Rewrite the rejected decision while reactivating it.",
    )
    adr.write_text(reactivated, encoding="utf-8")
    current = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    errors = accepted_history_ratchet_errors(base_payload, current)

    assert "ADR-0065 decision status cannot transition from rejected to accepted" in errors
    assert any("frozen accepted history changed" in error for error in errors)


def test_explicit_ci_base_and_local_missing_base_are_fail_closed(
    tmp_path: Path,
) -> None:
    adr = write_v2(tmp_path / "fixture", "0065")
    baseline = write_baseline(tmp_path / "fixture")
    registry = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)

    ci_result = audit_base_ratchets(
        registry,
        repo_root=tmp_path,
        baseline_path=baseline,
        environ={"CI": "1", "XPJ_AUDIT_BASE_REF": "missing"},
    )
    local_result = audit_base_ratchets(
        registry,
        repo_root=tmp_path,
        baseline_path=baseline,
        environ={},
    )

    assert ci_result.errors == ("cannot resolve exact ADR ratchet base 'missing'",)
    assert local_result.errors == (
        "cannot resolve local ADR ratchet base from main or origin/main",
    )


def test_calibration_commits_must_resolve_and_be_head_ancestors(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "adr@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "ADR Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "base"], cwd=tmp_path, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 legacy\n", encoding="utf-8")
    row = legacy_entry(legacy, "0001")
    row["reviewed_against_commit"] = commit
    baseline = write_baseline(
        tmp_path,
        [row],
        bootstrap_base_commit=commit,
        code_baseline=commit,
    )
    registry = build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)

    assert _calibration_commit_errors(registry, tmp_path) == []

    forged_entry = replace(registry.entries[0], reviewed_against_commit="2" * 40)
    forged = replace(registry, entries=(forged_entry,))
    assert _calibration_commit_errors(forged, tmp_path) == [
        f"ADR-0001 calibration review commit {'2' * 40!r} cannot be resolved exactly"
    ]

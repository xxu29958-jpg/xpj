from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from adr_contract_registry import (  # noqa: E402
    DECISIONS_DIR,
    LEGACY_BASELINE_PATH,
    RegistryError,
    build_registry,
)
from adr_contract_test_support import (  # noqa: E402
    baseline_payload,
    legacy_entry,
    valid_adr,
    write_baseline,
    write_v2,
)
from adr_contract_views import (  # noqa: E402
    ViewPaths,
    registry_json,
    stale_view_errors,
    write_views,
)


def test_repository_contract_registry_is_current() -> None:
    registry = build_registry(
        decisions_dir=DECISIONS_DIR,
        legacy_baseline_path=LEGACY_BASELINE_PATH,
    )

    assert len(registry.entries) == 72
    assert stale_view_errors(registry) == []
    entries = {entry.adr_id: entry for entry in registry.entries}
    amendments = {
        relation.target
        for relation in entries["0074"].relations
        if relation.kind == "amends"
    }
    assert {"0062", "0063"} <= amendments
    projected = {
        entry["id"]: entry for entry in json.loads(registry_json(registry))["entries"]
    }
    assert "非原子恢复标记" in projected["0062"]["declared_current_scope"]
    assert "非原子恢复标记" in projected["0062"]["current_scope"]
    assert "handoff 父目录 ACL 审查失败" in projected["0063"]["declared_current_scope"]
    assert "handoff 父目录 ACL 审查失败" in projected["0063"]["current_scope"]
    assert projected["0062"]["effective_amendments"][0]["source"] == "0074"
    assert projected["0062"]["implementation_status"] == "nonconformant"
    assert projected["0062"]["verification_status"] == "failed"
    assert projected["0063"]["implementation_status"] == "partial"
    assert projected["0063"]["verification_status"] == "failed"


def test_legacy_hash_ratchet_rejects_mutation(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 legacy\n", encoding="utf-8")
    baseline = write_baseline(tmp_path, [legacy_entry(legacy, "0001")])

    assert build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)
    legacy.write_text("# 0001 silently rewritten\n", encoding="utf-8")

    with pytest.raises(RegistryError, match="changed outside the legacy ratchet"):
        build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)


def test_new_legacy_debt_cannot_enter_without_migration(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    (decisions / "0066-new.md").write_text("# 0066 unversioned\n", encoding="utf-8")
    baseline = write_baseline(tmp_path)

    with pytest.raises(RegistryError, match="absent from legacy sources"):
        build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)


def test_closed_legacy_baseline_cannot_grow(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0066-legacy.md"
    legacy.write_text("# 0066 legacy\n", encoding="utf-8")
    baseline = write_baseline(tmp_path, [legacy_entry(legacy, "0066")])

    with pytest.raises(RegistryError, match="cannot be added to the closed legacy baseline"):
        build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)


def test_schema_v2_adr_cannot_overlap_frozen_legacy_sources(tmp_path: Path) -> None:
    schema_v2 = write_v2(tmp_path, "0061")
    baseline = write_baseline(tmp_path, [legacy_entry(schema_v2, "0061")])

    with pytest.raises(RegistryError, match="uses schema v2 but remains"):
        build_registry(decisions_dir=schema_v2.parent, legacy_baseline_path=baseline)


def test_relation_target_and_cycle_are_rejected(tmp_path: Path) -> None:
    missing = write_v2(
        tmp_path / "missing",
        "0065",
        relations=(("depends-on", "9999", "missing fixture"),),
    )
    missing_baseline = write_baseline(tmp_path / "missing")
    with pytest.raises(RegistryError, match="missing ADR-9999"):
        build_registry(
            decisions_dir=missing.parent,
            legacy_baseline_path=missing_baseline,
        )

    cycle_root = tmp_path / "cycle"
    first = write_v2(
        cycle_root,
        "0065",
        relations=(("depends-on", "0066", "cycle edge"),),
    )
    write_v2(
        cycle_root,
        "0066",
        relations=(("depends-on", "0065", "cycle edge"),),
    )
    cycle_baseline = write_baseline(cycle_root)
    with pytest.raises(RegistryError, match="ADR relation cycle"):
        build_registry(decisions_dir=first.parent, legacy_baseline_path=cycle_baseline)


def test_two_accepted_conflicting_decisions_are_merge_blocker(tmp_path: Path) -> None:
    first = write_v2(
        tmp_path,
        "0065",
        relations=(("conflicts-with", "0066", "mutually exclusive authority"),),
    )
    write_v2(tmp_path, "0066")
    baseline = write_baseline(tmp_path)

    with pytest.raises(RegistryError, match="accepted ADR-0065 conflicts with accepted ADR-0066"):
        build_registry(decisions_dir=first.parent, legacy_baseline_path=baseline)


def test_accepted_decision_cannot_depend_on_inactive_target(tmp_path: Path) -> None:
    source = write_v2(
        tmp_path,
        "0065",
        relations=(("depends-on", "0066", "normative dependency"),),
    )
    write_v2(
        tmp_path,
        "0066",
        decision_status="superseded",
        implementation_status="implemented",
        verification_status="stale",
    )
    baseline = write_baseline(tmp_path)

    with pytest.raises(RegistryError, match="depends on inactive ADR-0066"):
        build_registry(decisions_dir=source.parent, legacy_baseline_path=baseline)


def test_registry_json_is_deterministic(tmp_path: Path) -> None:
    second = write_v2(tmp_path, "0066")
    write_v2(tmp_path, "0065")
    baseline = write_baseline(tmp_path)

    first_render = registry_json(build_registry(decisions_dir=second.parent, legacy_baseline_path=baseline))
    second_render = registry_json(build_registry(decisions_dir=second.parent, legacy_baseline_path=baseline))

    assert first_render == second_render
    assert first_render.index('"id": "0065"') < first_render.index('"id": "0066"')


def test_accepted_amendment_projects_current_state_without_rewriting_target(
    tmp_path: Path,
) -> None:
    target = write_v2(tmp_path, "0065", implementation_status="implemented")
    write_v2(
        tmp_path,
        "0066",
        implementation_status="partial",
        relations=(("amends", "0065", "bounded current-state correction"),),
    )
    write_v2(
        tmp_path,
        "0067",
        implementation_status="nonconformant",
        verification_status="failed",
    )
    write_v2(
        tmp_path,
        "0068",
        implementation_status="implemented",
        verification_status="verified",
        relations=(("amends", "0067", "bounded verified correction"),),
    )
    baseline = write_baseline(tmp_path)

    registry = build_registry(decisions_dir=target.parent, legacy_baseline_path=baseline)
    payload = json.loads(registry_json(registry))
    entries = {entry["id"]: entry for entry in payload["entries"]}
    projected = entries["0065"]
    failed_projection = entries["0067"]

    assert projected["declared_current_scope"] == "Test-only contract scope"
    assert projected["declared_implementation_status"] == "implemented"
    assert projected["current_scope"].startswith(
        "ADR-0065 未被后继关系覆盖的 declared_current_scope：Test-only contract scope"
    )
    assert "ADR-0066 后继修订" in projected["current_scope"]
    assert projected["implementation_status"] == "partial"
    assert projected["effective_amendments"] == [
        {
            "source": "0066",
            "scope": "bounded current-state correction",
            "implementation_status": "partial",
            "verification_status": "unverified",
        }
    ]
    assert failed_projection["declared_implementation_status"] == "nonconformant"
    assert failed_projection["declared_verification_status"] == "failed"
    assert failed_projection["implementation_status"] == "nonconformant"
    assert failed_projection["verification_status"] == "failed"
    assert failed_projection["effective_amendments"] == [
        {
            "source": "0068",
            "scope": "bounded verified correction",
            "implementation_status": "implemented",
            "verification_status": "verified",
        }
    ]


def test_generated_view_mutation_is_detected(tmp_path: Path) -> None:
    adr = write_v2(tmp_path, "0065")
    baseline = write_baseline(tmp_path)
    registry = build_registry(decisions_dir=adr.parent, legacy_baseline_path=baseline)
    current = tmp_path / "docs" / "current"
    current.mkdir(parents=True)
    status = current / "ADR_STATUS.md"
    index = adr.parent / "README.md"
    status.write_text(
        "<!-- ADR_STATUS_METADATA_START -->\nold\n<!-- ADR_STATUS_METADATA_END -->\n"
        "<!-- ADR_STATUS_TABLE_START -->\nold\n<!-- ADR_STATUS_TABLE_END -->\n",
        encoding="utf-8",
    )
    index.write_text(
        "<!-- ADR_INDEX_TABLE_START -->\nold\n<!-- ADR_INDEX_TABLE_END -->\n"
        "<!-- ADR_NEXT_ID_START -->\nold\n<!-- ADR_NEXT_ID_END -->\n",
        encoding="utf-8",
    )
    paths = ViewPaths(
        registry=current / "adr-registry.json",
        status=status,
        index=index,
        graph=current / "ADR_DEPENDENCY_GRAPH.md",
        repo_root=tmp_path,
    )

    write_views(registry, paths=paths)
    assert stale_view_errors(registry, paths=paths) == []

    paths.status.write_text(
        paths.status.read_text(encoding="utf-8").replace(
            f"`{registry.code_baseline}`",
            "`0000000000000000000000000000000000000000`",
        ),
        encoding="utf-8",
    )
    assert stale_view_errors(registry, paths=paths) == [
        "generated ADR view is stale: docs/current/ADR_STATUS.md"
    ]
    write_views(registry, paths=paths)

    paths.graph.write_text("manual edit\n", encoding="utf-8")
    assert stale_view_errors(registry, paths=paths) == [
        "generated ADR view is stale: docs/current/ADR_DEPENDENCY_GRAPH.md"
    ]


def test_noncanonical_decision_markdown_cannot_bypass_registry(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    (decisions / "ADR-0066-hidden.md").write_text(valid_adr("0066"), encoding="utf-8")
    baseline = write_baseline(tmp_path)

    with pytest.raises(RegistryError, match="invalid ADR filename"):
        build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)


def test_legacy_baseline_integer_fields_reject_boolean(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    baseline = write_baseline(tmp_path)
    payload = baseline_payload()
    payload["schema_version"] = True
    baseline.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RegistryError, match="schema_version.*integer"):
        build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)


def test_legacy_adr_cannot_claim_verified_without_stable_clauses(tmp_path: Path) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 legacy\n", encoding="utf-8")
    row = legacy_entry(legacy, "0001")
    row["verification_status"] = "verified"
    baseline = write_baseline(tmp_path, [row])

    with pytest.raises(RegistryError, match="cannot be verified without stable clauses"):
        build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)


@pytest.mark.parametrize("field", ["portfolio", "entry"])
def test_calibration_review_dates_cannot_be_in_the_future(
    tmp_path: Path, field: str
) -> None:
    decisions = tmp_path / "docs" / "DECISIONS"
    decisions.mkdir(parents=True)
    legacy = decisions / "0001-legacy.md"
    legacy.write_text("# 0001 legacy\n", encoding="utf-8")
    row = legacy_entry(legacy, "0001")
    if field == "entry":
        row["reviewed_at"] = "2999-01-01"
    baseline = write_baseline(tmp_path, [row])
    if field == "portfolio":
        calibration_path = baseline.with_name("legacy-calibration.json")
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        calibration["portfolio_reviewed_at"] = "2999-01-01"
        calibration_path.write_text(json.dumps(calibration), encoding="utf-8")

    with pytest.raises(RegistryError, match="must not be in the future"):
        build_registry(decisions_dir=decisions, legacy_baseline_path=baseline)

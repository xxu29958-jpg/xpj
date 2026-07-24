from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_script
from tests._infra.paths import REPOSITORY_ROOT

dependency_audit = load_ci_script("android_dependency_audit.py")
workflow_yaml = load_ci_script("ci_gap_workflow_yaml.py")


def _seed_database(path: Path, *, updated_at: int, content: str = "trusted") -> None:
    path.mkdir(parents=True)
    (path / "odc.mv.db").write_text(content, encoding="utf-8")
    (path / dependency_audit.FRESHNESS_MARKER).write_text(
        f"{updated_at}\n",
        encoding="ascii",
    )


def test_exact_hit_and_secretless_restore_scan_only_a_copy(tmp_path: Path) -> None:
    now = 2_000_000
    for name, cache_hit, has_api_key in (
        ("exact", True, True),
        ("fork", False, False),
    ):
        trusted = tmp_path / name / "trusted"
        _seed_database(trusted, updated_at=now)

        def run_task(
            task: str,
            database: Path,
            expected_trusted: Path = trusted,
        ) -> int:
            assert task == "dependencyCheckAnalyze"
            assert database != expected_trusted
            (database / "odc.mv.db").write_text("scan mutation", encoding="utf-8")
            return 0

        assert not dependency_audit.run_dependency_audit(
            trusted=trusted,
            work=tmp_path / name / "work",
            cache_hit=cache_hit,
            has_api_key=has_api_key,
            run_task=run_task,
            now=now,
        )
        assert (trusted / "odc.mv.db").read_text(encoding="utf-8") == "trusted"


def test_secretless_restore_rejects_stale_database(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    now = 2_000_000
    _seed_database(trusted, updated_at=now - 49 * 60 * 60)

    with pytest.raises(dependency_audit.AuditError, match="freshness window"):
        dependency_audit.run_dependency_audit(
            trusted=trusted,
            work=tmp_path / "work",
            cache_hit=False,
            has_api_key=False,
            run_task=lambda _task, _database: 0,
            now=now,
        )


def test_failed_update_preserves_trusted_database(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    _seed_database(trusted, updated_at=1, content="before")

    def run_task(task: str, database: Path) -> int:
        assert task == "dependencyCheckUpdate"
        (database / "odc.mv.db").write_text("partial update", encoding="utf-8")
        return 1

    with pytest.raises(dependency_audit.AuditError, match="NVD update failed"):
        dependency_audit.run_dependency_audit(
            trusted=trusted,
            work=tmp_path / "work",
            cache_hit=False,
            has_api_key=True,
            run_task=run_task,
            now=2_000_000,
        )
    assert (trusted / "odc.mv.db").read_text(encoding="utf-8") == "before"


def test_failed_analysis_does_not_promote_candidate(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    _seed_database(trusted, updated_at=1, content="before")

    def run_task(task: str, database: Path) -> int:
        if task == "dependencyCheckUpdate":
            (database / "odc.mv.db").write_text("refreshed", encoding="utf-8")
            return 0
        return 1

    with pytest.raises(dependency_audit.AuditError, match="analysis failed"):
        dependency_audit.run_dependency_audit(
            trusted=trusted,
            work=tmp_path / "work",
            cache_hit=False,
            has_api_key=True,
            run_task=run_task,
            now=2_000_000,
        )
    assert (trusted / "odc.mv.db").read_text(encoding="utf-8") == "before"


def test_successful_refresh_promotes_validated_candidate(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    now = 2_000_000
    _seed_database(trusted, updated_at=1, content="before")
    observed: list[str] = []

    def run_task(task: str, database: Path) -> int:
        observed.append(task)
        if task == "dependencyCheckUpdate":
            (database / "odc.mv.db").write_text("refreshed", encoding="utf-8")
        return 0

    assert dependency_audit.run_dependency_audit(
        trusted=trusted,
        work=tmp_path / "work",
        cache_hit=False,
        has_api_key=True,
        run_task=run_task,
        now=now,
    )
    assert observed == ["dependencyCheckUpdate", "dependencyCheckAnalyze"]
    assert (trusted / "odc.mv.db").read_text(encoding="utf-8") == "refreshed"
    assert int(
        (trusted / dependency_audit.FRESHNESS_MARKER).read_text(encoding="ascii")
    ) == now


def test_workflow_restores_and_saves_only_validated_nvd_data() -> None:
    workflow = workflow_yaml.load_workflow(
        REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
    )
    android = workflow["jobs"]["android"]
    steps = {step.get("id"): step for step in android["steps"] if step.get("id")}

    assert "NVD_API_KEY" not in android["env"]
    assert steps["nvd-cache"]["uses"].startswith("actions/cache/restore@")
    assert steps["nvd-cache-save"]["uses"].startswith("actions/cache/save@")
    assert steps["nvd-cache"]["with"]["key"] == steps["nvd-cache-save"]["with"]["key"]
    assert "steps.nvd-key.outputs.version" in steps["nvd-cache"]["with"]["key"]
    assert steps["nvd-cache-save"]["if"] == (
        "steps.dependency-audit.outputs.cache-save == 'true'"
    )
    audit_step = steps["dependency-audit"]
    assert tuple(audit_step["env"]) == ("NVD_API_KEY",)
    command = shlex.split(audit_step["run"].replace("\\\n", " "))
    assert command[:2] == ["python", "../backend/scripts/android_dependency_audit.py"]
    assert "--cache-hit" in command

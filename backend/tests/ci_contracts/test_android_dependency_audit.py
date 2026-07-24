from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_script
from tests._infra.paths import REPOSITORY_ROOT

dependency_audit = load_ci_script("android_dependency_audit.py")
workflow_yaml = load_ci_script("ci_gap_workflow_yaml.py")


def _seed_database(path: Path, content: str = "trusted") -> None:
    data_dir = path / "11.0"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "odc.mv.db").write_text(content, encoding="utf-8")


def test_trusted_main_artifact_scans_only_a_copy(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    _seed_database(trusted)

    def run_task(task: str, database: Path) -> int:
        assert task == dependency_audit.SCAN_TASK
        assert database != trusted
        (database / "11.0" / "odc.mv.db").write_text(
            "scan mutation",
            encoding="utf-8",
        )
        return 0

    assert dependency_audit.run_dependency_audit(
        trusted=trusted,
        work=tmp_path / "work",
        artifact_present=True,
        has_api_key=False,
        run_task=run_task,
    ) == "trusted-artifact"
    assert (trusted / "11.0" / "odc.mv.db").read_text(encoding="utf-8") == "trusted"


@pytest.mark.parametrize("payload_count", [0, 2])
def test_secretless_audit_rejects_malformed_artifact(
    tmp_path: Path,
    payload_count: int,
) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    for index in range(payload_count):
        _seed_database(trusted / str(index))

    with pytest.raises(dependency_audit.ArtifactError):
        dependency_audit.run_dependency_audit(
            trusted=trusted,
            work=tmp_path / "work",
            artifact_present=True,
            has_api_key=False,
            run_task=lambda _task, _database: 0,
        )


def test_secretless_audit_requires_a_trusted_artifact(tmp_path: Path) -> None:
    with pytest.raises(dependency_audit.AuditError, match="artifact or NVD_API_KEY"):
        dependency_audit.run_dependency_audit(
            trusted=tmp_path / "missing",
            work=tmp_path / "work",
            artifact_present=False,
            has_api_key=False,
            run_task=lambda _task, _database: 0,
        )


def test_audit_refuses_existing_work_directory_without_deleting_it(
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    marker = work / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(dependency_audit.AuditError, match="must not already exist"):
        dependency_audit.run_dependency_audit(
            trusted=tmp_path / "missing",
            work=work,
            artifact_present=False,
            has_api_key=True,
            run_task=lambda _task, _database: 0,
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_audit_refuses_symlink_work_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    link = tmp_path / "work-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(dependency_audit.AuditError, match="must not already exist"):
        dependency_audit.run_dependency_audit(
            trusted=tmp_path / "missing",
            work=link,
            artifact_present=False,
            has_api_key=True,
            run_task=lambda _task, _database: 0,
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_keyed_audit_refreshes_in_isolation_when_artifact_is_invalid(
    tmp_path: Path,
) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    marker = trusted / "invalid.txt"
    marker.write_text("do not mutate", encoding="utf-8")
    observed: list[str] = []

    def run_task(task: str, database: Path) -> int:
        observed.append(task)
        if task == "dependencyCheckUpdate":
            _seed_database(database, "fresh")
        return 0

    assert dependency_audit.run_dependency_audit(
        trusted=trusted,
        work=tmp_path / "work",
        artifact_present=True,
        has_api_key=True,
        run_task=run_task,
    ) == "live-refresh"
    assert observed == ["dependencyCheckUpdate", dependency_audit.SCAN_TASK]
    assert marker.read_text(encoding="utf-8") == "do not mutate"


@pytest.mark.parametrize("failed_task", ["dependencyCheckUpdate", dependency_audit.SCAN_TASK])
def test_failed_refresh_removes_partial_candidate(
    tmp_path: Path,
    failed_task: str,
) -> None:
    work = tmp_path / "work"

    def run_task(task: str, database: Path) -> int:
        _seed_database(database, "partial")
        return 1 if task == failed_task else 0

    with pytest.raises(dependency_audit.AuditError):
        dependency_audit.run_dependency_audit(
            trusted=tmp_path / "missing",
            work=work,
            artifact_present=False,
            has_api_key=True,
            run_task=run_task,
        )
    assert not (work / "candidate").exists()


def test_producer_publishes_only_after_update_and_analysis(tmp_path: Path) -> None:
    output = tmp_path / "output"
    seed = tmp_path / "seed"
    _seed_database(seed, "previous")
    observed: list[str] = []

    def run_task(task: str, database: Path) -> int:
        observed.append(task)
        if task == "dependencyCheckUpdate":
            assert (database / "11.0" / "odc.mv.db").read_text(
                encoding="utf-8"
            ) == "previous"
            (database / "11.0" / "odc.mv.db").write_text(
                "fresh",
                encoding="utf-8",
            )
        return 0

    dependency_audit.produce_dependency_database(
        output=output,
        seed=seed,
        run_task=run_task,
    )

    assert observed == ["dependencyCheckUpdate", dependency_audit.SCAN_TASK]
    assert (output / "11.0" / "odc.mv.db").is_file()


def test_producer_refuses_existing_output_without_deleting_it(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(dependency_audit.AuditError, match="must not already exist"):
        dependency_audit.produce_dependency_database(
            output=output,
            run_task=lambda _task, _database: 0,
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_gradle_adapter_forces_refresh_and_offline_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocations: list[tuple[list[str], dict[str, object]]] = []
    android_root = tmp_path / "android"
    report = android_root / "build" / "reports" / "dependency-check-report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {
                        "packages": [
                            {"id": "pkg:maven/com.squareup.retrofit2/retrofit@3.0.0"}
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog = android_root / "gradle" / "libs.versions.toml"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        """
[versions]
retrofit = "3.0.0"
[libraries]
retrofit = { module = "com.squareup.retrofit2:retrofit", version.ref = "retrofit" }
""".strip(),
        encoding="utf-8",
    )

    class FakeProcess:
        returncode = 0
        pid = 123

        def communicate(self, timeout: int | None = None) -> tuple[str, None]:
            assert timeout in {
                dependency_audit.SCAN_TIMEOUT_SECONDS,
                dependency_audit.UPDATE_TIMEOUT_SECONDS,
            }
            return "ok\n", None

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        invocations.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(dependency_audit.subprocess, "Popen", fake_popen)
    run_task = dependency_audit._run_gradle_factory(
        android_root / "gradlew",
        tmp_path / "audit.log",
    )

    assert run_task("dependencyCheckUpdate", tmp_path / "update") == 0
    assert run_task(dependency_audit.SCAN_TASK, tmp_path / "scan") == 0
    producer_task = dependency_audit._run_gradle_factory(
        android_root / "gradlew",
        tmp_path / "producer.log",
        fail_on_findings=False,
    )
    assert producer_task(dependency_audit.SCAN_TASK, tmp_path / "producer") == 0
    assert "--no-daemon" in invocations[0][0]
    assert "--max-workers=2" in invocations[0][0]
    assert "-PdependencyCheckNvdValidForHours=0" in invocations[0][0]
    assert "-PdependencyCheckAutoUpdate=false" in invocations[1][0]
    assert "-PdependencyCheckFailBuildOnCVSS=11" not in invocations[1][0]
    assert "-PdependencyCheckFailBuildOnCVSS=11" in invocations[2][0]
    assert invocations[0][1]["stdout"] == dependency_audit.subprocess.PIPE
    assert invocations[0][1]["stderr"] == dependency_audit.subprocess.STDOUT
    assert invocations[0][1]["start_new_session"] is (os.name != "nt")


def test_terminated_gradle_process_has_a_bounded_output_drain() -> None:
    class StuckProcess:
        def __init__(self) -> None:
            self.communicate_calls = 0
            self.kill_calls = 0

        def communicate(self, timeout: int | None = None) -> tuple[str, None]:
            assert timeout == 30
            self.communicate_calls += 1
            raise dependency_audit.subprocess.TimeoutExpired("gradle", timeout)

        def kill(self) -> None:
            self.kill_calls += 1

    process = StuckProcess()

    output = dependency_audit._drain_terminated_process(process)

    assert process.communicate_calls == 2
    assert process.kill_calls == 1
    assert "could not be drained" in output


def test_dependency_report_must_contain_the_catalog_app_anchor(tmp_path: Path) -> None:
    catalog = tmp_path / "libs.versions.toml"
    catalog.write_text(
        """
[versions]
retrofit = "3.0.0"
[libraries]
retrofit = { module = "com.squareup.retrofit2:retrofit", version.ref = "retrofit" }
""".strip(),
        encoding="utf-8",
    )
    report = tmp_path / "dependency-check-report.json"
    report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {"packages": [{"id": "pkg:maven/com.example/other@1.0"}]}
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(dependency_audit.AuditError, match="Android app anchor"):
        dependency_audit._require_app_dependency_report(report, catalog)


def test_workflows_publish_on_main_and_consume_versioned_immutable_artifacts() -> None:
    ci = workflow_yaml.load_workflow(
        REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
    )
    producer = workflow_yaml.load_workflow(
        REPOSITORY_ROOT / ".github" / "workflows" / "nvd-database.yml"
    )
    android = ci["jobs"]["android"]
    steps = android["steps"]
    by_id = {step.get("id"): step for step in steps if step.get("id")}

    assert android["permissions"] == {"actions": "read", "contents": "read"}
    assert not any("actions/cache" in step.get("uses", "") for step in steps)
    resolver = by_id["nvd-source"]
    assert "resolve_nvd_artifact.py" in resolver["run"]
    assert "ticketbox-nvd-database-v${{" in resolver["run"]
    assert resolver["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}
    sdk_setup = next(step for step in steps if step["name"] == "Install Android SDK packages")
    assert steps.index(resolver) < steps.index(sdk_setup)
    preflight = next(step for step in steps if step["name"] == "Require dependency audit source")
    assert preflight["if"] == "steps.nvd-source.outputs.found != 'true'"
    downloader = next(
        step for step in steps if "actions/download-artifact@" in step.get("uses", "")
    )
    assert downloader["if"] == "steps.nvd-source.outputs.found == 'true'"
    assert downloader["with"]["artifact-ids"] == (
        "${{ steps.nvd-source.outputs.artifact_id }}"
    )
    assert downloader["with"]["digest-mismatch"] == "error"
    audit = next(step for step in steps if step["name"] == "Dependency vulnerability scan")
    command = shlex.split(audit["run"].replace("\\\n", " "))
    assert command[:3] == [
        "python",
        "../backend/scripts/android_dependency_audit.py",
        "scan",
    ]
    assert "--artifact-present" in command
    assert not any(argument.startswith("--source-") for argument in command)

    produce = producer["jobs"]["produce"]
    produce_steps = produce["steps"]
    assert producer["permissions"] == {"actions": "read", "contents": "read"}
    assert "pull_request" not in producer["on"]
    assert produce["if"] == "github.ref == 'refs/heads/main'"
    assert produce["timeout-minutes"] == 40
    assert producer["concurrency"]["group"] == "android-nvd-database-${{ github.ref }}"
    checkout = next(step for step in produce_steps if step["name"] == "Checkout main")
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    produce_command = next(
        step["run"]
        for step in produce_steps
        if step["name"] == "Produce and validate NVD database"
    )
    assert "android_dependency_audit.py produce" in produce_command
    assert "--seed-dir" in produce_command
    assert "--seed-present" in produce_command
    assert "--source-" not in produce_command
    uploader = next(
        step for step in produce_steps if "actions/upload-artifact@" in step.get("uses", "")
    )
    assert uploader["with"]["name"] == (
        "ticketbox-nvd-database-v${{ steps.dependency-check-version.outputs.version }}"
    )
    assert uploader["with"]["if-no-files-found"] == "error"

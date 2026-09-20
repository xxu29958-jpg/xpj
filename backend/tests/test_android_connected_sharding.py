from __future__ import annotations

import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _steps(job: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(step["name"]): step for step in job["steps"]}


def test_connected_workflow_runs_two_isolated_qualified_shards() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "android-connected-test.yml").read_text(
            encoding="utf-8"
        )
    )
    jobs = workflow["jobs"]
    execution = jobs["connected_execution"]
    assert execution["strategy"] == {
        "fail-fast": False,
        "matrix": {
            "shard": [
                {"index": 0, "count": 2, "label": "1/2"},
                {"index": 1, "count": 2, "label": "2/2"},
            ]
        },
    }
    assert execution["timeout-minutes"] == 45
    assert "outputs" not in execution
    steps = _steps(execution)
    run = steps["Run connected test"]
    assert run["timeout-minutes"] == 35
    tokens = shlex.split(str(run["with"]["script"]))
    assert "30m" in tokens
    assert "-Pandroid.testInstrumentationRunnerArguments.numShards=${{ matrix.shard.count }}" in tokens
    assert "-Pandroid.testInstrumentationRunnerArguments.shardIndex=${{ matrix.shard.index }}" in tokens
    assert tokens[-1] == ":app:connectedGrayDebugAndroidTest"
    assert steps["Upload connected shard evidence"]["if"] == "${{ always() && !cancelled() }}"
    assert steps["Upload connected shard evidence"]["with"]["name"] == (
        "connected-shard-${{ matrix.shard.index }}-attempt-${{ github.run_attempt }}"
    )
    artifact_names = [
        step["with"]["name"]
        for step in execution["steps"]
        if "actions/upload-artifact@" in step.get("uses", "")
    ]
    expanded_names = [
        template.replace("${{ matrix.shard.index }}", str(index)).replace(
            "${{ github.run_attempt }}", str(attempt)
        )
        for template in artifact_names
        for index in range(2)
        for attempt in (1, 2)
    ]
    assert len(set(expanded_names)) == len(expanded_names)

    qualification = jobs["connected_qualification"]
    assert qualification["needs"] == ["scope", "connected_execution"]
    qualification_steps = _steps(qualification)
    assert qualification_steps["Download connected shard evidence"]["with"]["pattern"] == "connected-shard-*"
    verify = qualification_steps["Qualify connected shard union"]
    assert " connected-shards " in f" {verify['run']} "
    assert verify["env"]["EXPECTED_SHARD_COUNT"] == "2"

    required = jobs["connected"]
    assert set(required["needs"]) == {
        "scope",
        "connected_execution",
        "connected_qualification",
    }
    enforce = _steps(required)["Enforce Connected result"]
    assert "--lane QUALIFICATION" in enforce["run"]
    assert "EXECUTION_SHA" not in enforce["env"]


def test_gradle_keeps_connected_timeout_and_shard_evidence_hooks() -> None:
    build = (ROOT / "android" / "app" / "build.gradle.kts").read_text(
        encoding="utf-8"
    )
    assert "timeout.set(Duration.ofMinutes(24))" in build
    assert "timeout.set(Duration.ofMinutes(5))" in build
    assert "ticketbox-connected-discovery.txt" in build
    assert "ticketbox-connected-discovery-exit-code.txt" in build
    assert "ticketbox-connected-shard-evidence.json" in build
    assert '"connected-shard"' in build
    assert '"connected"' in build
    assert "androidTestBaselineFile.absolutePath" in build
    assert 'System.getenv("CI")' in build
    assert '?: "0".repeat(40)' not in build
    assert '?: "local"' not in build
    assert build.index('"the post-test process-exit snapshot"') < build.index(
        "captureTicketboxConnectedDiscovery(\n                adb,\n                captureSerials,"
    )

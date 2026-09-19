from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import ci_run_timing

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ROOT = Path(__file__).resolve().parents[2]


def _job(**fields: object) -> dict:
    row: dict[str, object] = {
        "id": 1,
        "name": "Backend contracts",
        "conclusion": "success",
        "status": "completed",
        "run_attempt": 1,
        "run_id": 100,
        "head_sha": "a" * 40,
        "workflow_name": "CI",
        "labels": ["ubuntu-latest"],
        "created_at": "2026-09-18T02:00:00Z",
        "started_at": "2026-09-18T02:01:00Z",
        "completed_at": "2026-09-18T02:11:00Z",
    }
    row.update(fields)
    return row


def _audit_lane(name: str = "repository-weight", returncode: int = 0) -> dict[str, object]:
    return {
        "lane": name,
        "filename": f"_audit_{name.replace('-', '_')}.py",
        "returncode": returncode,
        "complete": True,
    }


def _audit_run(lanes: list[str] | None = None, *, returncode: int = 0, complete: bool = True) -> dict[str, object]:
    names = list(lanes or ["repository-weight"])
    return {
        "expected_lanes": names,
        "expected_lane_count": len(names),
        "completed_lane_count": len(names),
        "overall_returncode": returncode,
        "complete": complete,
    }


def _step(name: str, started: str, completed: str) -> dict[str, object]:
    return {
        "name": name,
        "conclusion": "success",
        "started_at": started,
        "completed_at": completed,
    }


def _connected_steps(*, run_started: str, run_ended: str) -> list[dict[str, object]]:
    return [
        _step("Verify qualification SHA", "2026-09-18T02:02:00Z", "2026-09-18T02:02:10Z"),
        _step("Set up Java", "2026-09-18T02:03:00Z", "2026-09-18T02:03:20Z"),
        _step("Accept Android SDK licenses", "2026-09-18T02:04:00Z", "2026-09-18T02:04:30Z"),
        _step("Precompile connected APKs", "2026-09-18T02:10:00Z", "2026-09-18T02:14:00Z"),
        _step("Set up Gradle", "2026-09-18T02:14:05Z", "2026-09-18T02:14:20Z"),
        _step("Run connected test", run_started, run_ended),
        _step("Enforce Connected result", "2026-09-18T02:36:00Z", "2026-09-18T02:36:05Z"),
    ]


def test_attempt_listing_does_not_double_count_inherited_jobs() -> None:
    first = _job(
        created_at="2026-09-18T02:52:30Z",
        started_at="2026-09-18T02:52:34Z",
        completed_at="2026-09-18T02:59:38Z",
    )
    latest = {**first, "run_attempt": 2, "created_at": "2026-09-18T03:35:00Z"}
    summary = ci_run_timing.summarize_jobs([latest], attempt=2, previous_jobs=[first])
    assert summary["jobs"][0]["inherited"] is True
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is True


def test_different_id_inherited_job_contributes_zero_minutes() -> None:
    first = _job(
        id=105463540564,
        name="CI scope",
        started_at="2026-09-18T02:52:23Z",
        completed_at="2026-09-18T02:52:32Z",
        created_at="2026-09-18T02:52:20Z",
        steps=[{
            "name": "Resolve heavy-job scope",
            "conclusion": "success",
            "started_at": "2026-09-18T02:52:24Z",
            "completed_at": "2026-09-18T02:52:31Z",
        }],
    )
    inherited = {**first, "id": 105471586858, "run_attempt": 2, "created_at": "2026-09-18T03:35:00Z"}
    summary = ci_run_timing.summarize_jobs([inherited], attempt=2, previous_jobs=[first])
    assert summary["jobs"][0]["inherited"] is True
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is True


def test_attempt_two_without_previous_evidence_is_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs([_job(run_attempt=2)], attempt=2)
    assert summary["complete"] is False
    assert summary["runner_execution_minutes"] == 0
    assert any("previous-attempt evidence" in item for item in summary["incomplete"])


def test_timed_out_execution_is_counted_separately() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(conclusion="timed_out", started_at="2026-09-18T02:00:00Z", completed_at="2026-09-18T02:10:00Z")],
        attempt=1,
    )
    assert summary["timed_out_execution_minutes"] == 10
    assert summary["by_conclusion"]["timed_out"] == 10
    assert summary["other_execution_minutes"] == 0
    assert summary["complete"] is True


def test_missing_shared_identity_is_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs(
        [{
            "id": 9,
            "name": "anonymous",
            "conclusion": "success",
            "status": "completed",
            "started_at": "2026-09-18T02:00:00Z",
            "completed_at": "2026-09-18T02:10:00Z",
        }],
        attempt=1,
    )
    assert summary["complete"] is False
    assert summary["runner_execution_minutes"] == 0


def test_successful_step_without_timestamps_is_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(steps=[{"name": "Audit", "conclusion": "success", "started_at": None, "completed_at": None}])],
        attempt=1,
    )
    assert summary["complete"] is False
    assert summary["step_timing_complete"] is False
    assert summary["runner_execution_minutes"] == 10


def test_inverted_timestamps_are_incomplete_not_silently_zeroed() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(started_at="2026-09-18T04:00:00Z", completed_at="2026-09-18T03:00:00Z")],
        attempt=1,
    )
    assert summary["jobs"][0]["inverted"] is True
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False


def test_step_inversion_is_incomplete_and_job_interval_still_billed() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(steps=[{
            "name": "Audit",
            "conclusion": "success",
            "started_at": "2026-09-18T02:10:00Z",
            "completed_at": "2026-09-18T02:01:00Z",
        }])],
        attempt=1,
    )
    assert summary["complete"] is False
    assert summary["step_timing_complete"] is False
    assert summary["runner_execution_minutes"] == 10


def test_mixed_run_id_does_not_bill() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(run_id=1), _job(id=2, name="Android", run_id=2)],
        attempt=1,
    )
    assert summary["complete"] is False
    assert summary["runner_execution_minutes"] == 0


def test_cancelled_consumed_time_is_listed_separately() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(name="Android", conclusion="cancelled", started_at="2026-09-18T02:00:00Z", completed_at="2026-09-18T02:10:00Z")],
        attempt=1,
    )
    assert summary["cancelled_execution_minutes"] == 10
    assert summary["complete"] is True


def test_failed_cancelled_and_skipped_totals_are_distinct() -> None:
    summary = ci_run_timing.summarize_jobs(
        [
            _job(id=1, name="ok", conclusion="success"),
            _job(id=2, name="bad", conclusion="failure", started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:06:00Z"),
            _job(id=3, name="stop", conclusion="cancelled", started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:04:00Z"),
            _job(id=4, name="skip", conclusion="skipped", started_at=None, completed_at=None),
        ],
        attempt=1,
    )
    assert summary["success_execution_minutes"] == 10
    assert summary["failure_execution_minutes"] == 5
    assert summary["cancelled_consumed_minutes"] == 3
    assert summary["skipped_jobs"] == ["skip"]
    assert summary["complete"] is True


def test_platform_minutes_are_split_by_runner_label() -> None:
    summary = ci_run_timing.summarize_jobs(
        [
            _job(id=1, name="ubuntu", labels=["ubuntu-latest"]),
            _job(
                id=2, name="windows", labels=["windows-latest"],
                started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:05:00Z",
            ),
        ],
        attempt=1,
    )
    assert summary["by_platform"]["ubuntu-latest"] == 10
    assert summary["by_platform"]["windows-latest"] == 4
    assert summary["runner_execution_minutes"] == 14


class _FakeResponse:
    def __init__(self, payload: dict | bytes) -> None:
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def test_github_job_fetch_paginates() -> None:
    def opener(request):
        query = request.full_url.rsplit("&page=", 1)[-1]
        if query == "1":
            return _FakeResponse({"jobs": [_job(id=index, name=f"job-{index}") for index in range(100)]})
        return _FakeResponse({"jobs": [_job(id=2, name="two")]})

    jobs = ci_run_timing.fetch_github_jobs("o/r", 9, 1, "token", urlopen=opener)
    assert len(jobs) == 101
    assert jobs[-1]["name"] == "two"


def test_cli_reads_fixture_jobs(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job(
        id=4, name="Connected",
        started_at="2026-09-18T02:53:19Z",
        completed_at="2026-09-18T03:15:53Z",
        created_at="2026-09-18T02:53:00Z",
        steps=[{
            "name": "Run connected test",
            "conclusion": "success",
            "started_at": "2026-09-18T02:57:33Z",
            "completed_at": "2026-09-18T03:15:34Z",
        }],
    )]}), encoding="utf-8")
    output = tmp_path / "timing.json"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "ci_run_timing.py"),
            "--jobs-json", str(jobs), "--attempt", "1",
            "--output-json", str(output),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == 2
    assert payload["runner_execution"]["known_minutes"] > 0
    assert payload["identity_complete"] is False


def test_cli_writes_json_when_jobs_input_is_missing(tmp_path: Path) -> None:
    output = tmp_path / "timing.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "ci_run_timing.py"), "--output-json", str(output)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["complete"] is False
    assert payload["identity_complete"] is False


def test_required_gate_wait_uses_last_required_check() -> None:
    ci = {
        "metadata": {
            "id": 1, "name": "CI", "event": "pull_request", "head_sha": "a" * 40,
            "status": "completed", "conclusion": "success", "run_attempt": 1,
            "created_at": "2026-09-18T02:00:00Z", "run_started_at": "2026-09-18T02:00:05Z",
            "pull_requests": [{"base": {"sha": "d" * 40}}],
        },
        "checkout_sha": "b" * 40,
        "jobs": [
            _job(name="Backend", started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:11:00Z"),
            _job(id=2, name="Android", started_at="2026-09-18T02:02:00Z", completed_at="2026-09-18T02:20:00Z"),
        ],
        "attempt": 1,
    }
    connected = {
        "metadata": {
            "id": 2, "name": "Android Connected Test", "event": "pull_request", "head_sha": "a" * 40,
            "status": "completed", "conclusion": "success", "run_attempt": 1,
            "created_at": "2026-09-18T02:00:10Z", "run_started_at": "2026-09-18T02:00:12Z",
            "pull_requests": [{"base": {"sha": "d" * 40}}],
        },
        "checkout_sha": "b" * 40,
        "jobs": [_job(
            id=9, name="Connected (emulator)", workflow_name="Android Connected Test",
            started_at="2026-09-18T02:30:00Z", completed_at="2026-09-18T02:40:00Z",
        )],
        "attempt": 1,
    }
    codeql = {
        "metadata": {
            "id": 3, "name": "CodeQL", "event": "pull_request", "head_sha": "a" * 40,
            "status": "completed", "conclusion": "success", "run_attempt": 1,
            "created_at": "2026-09-18T02:00:08Z", "run_started_at": "2026-09-18T02:00:09Z",
            "pull_requests": [{"base": {"sha": "d" * 40}}],
        },
        "checkout_sha": "b" * 40,
        "jobs": [_job(
            id=11, name="CodeQL", workflow_name="CodeQL",
            started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:18:00Z",
        )],
        "attempt": 1,
    }
    report = ci_run_timing.build_report(
        [ci, connected, codeql],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend", "Android", "CodeQL", "Connected (emulator)"],
    )
    wait = report["required_gate_wait"]
    assert wait["complete"] is True
    assert wait["trigger_created_at"].startswith("2026-09-18T02:00:00")
    assert wait["first_workflow_started_at"].startswith("2026-09-18T02:00:05")
    assert wait["elapsed_from_created_s"] == 2400.0
    assert wait["elapsed_from_started_s"] == 2395.0
    assert wait["missing_checks"] == []
    assert wait["required_checks"] == ["Backend", "Android", "CodeQL", "Connected (emulator)"]
    assert wait["required_check_source"] == "explicit_cli"
    assert report["identity_complete"] is True
    assert report["complete"] is True
    workflow = report["workflows"][0]
    for key in (
        "event", "source_sha", "checkout_sha", "base_sha", "created_at",
        "run_started_at", "final_job_completed_at", "status", "conclusion", "attempts",
    ):
        assert key in workflow
    assert workflow["final_job_completed_at_kind"] == "derived_from_job_completed_at"


def test_missing_required_check_does_not_publish_complete_total() -> None:
    bundle = {
        "metadata": {
            "id": 1, "name": "CI", "event": "pull_request", "head_sha": "a" * 40,
            "status": "completed", "conclusion": "success", "run_attempt": 1,
            "created_at": "2026-09-18T02:00:00Z", "run_started_at": "2026-09-18T02:00:05Z",
            "pull_requests": [{"base": {"sha": "d" * 40}}],
        },
        "jobs": [_job(name="Backend")],
        "attempt": 1,
    }
    report = ci_run_timing.build_report(
        [bundle],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend", "Connected (emulator)"],
    )
    assert report["required_gate_wait"]["complete"] is False
    assert report["required_gate_wait"]["missing_checks"] == ["Connected (emulator)"]
    assert report["runner_execution"]["known_minutes"] == 10
    assert report["complete"] is False


def test_in_progress_run_is_incomplete() -> None:
    bundle = {
        "metadata": {
            "id": 8, "name": "CI", "event": "push", "head_sha": "a" * 40,
            "status": "in_progress", "conclusion": None, "run_attempt": 1,
            "created_at": "2026-09-18T02:00:00Z",
        },
        "jobs": [_job()],
        "attempt": 1,
    }
    report = ci_run_timing.build_report([bundle], repository="xxu29958-jpg/xpj")
    assert report["complete"] is False
    assert any("unfinished" in item for item in report["incomplete_reasons"])


def test_android_phases_are_direct_combined_or_unknown() -> None:
    jobs = [
        _job(
            name="Connected execution",
            workflow_name="Android Connected Test",
            steps=[
                {
                    "name": "Verify qualification SHA",
                    "conclusion": "success",
                    "started_at": "2026-09-18T02:02:00Z",
                    "completed_at": "2026-09-18T02:02:10Z",
                },
                {
                    "name": "Set up Java",
                    "conclusion": "success",
                    "started_at": "2026-09-18T02:03:00Z",
                    "completed_at": "2026-09-18T02:03:20Z",
                },
                {
                    "name": "Accept Android SDK licenses",
                    "conclusion": "success",
                    "started_at": "2026-09-18T02:04:00Z",
                    "completed_at": "2026-09-18T02:04:30Z",
                },
                {
                    "name": "Precompile connected APKs",
                    "conclusion": "success",
                    "started_at": "2026-09-18T02:10:00Z",
                    "completed_at": "2026-09-18T02:14:00Z",
                },
                {
                    "name": "Run connected test",
                    "conclusion": "success",
                    "started_at": "2026-09-18T02:15:00Z",
                    "completed_at": "2026-09-18T02:35:00Z",
                },
                {
                    "name": "Enforce Connected result",
                    "conclusion": "success",
                    "started_at": "2026-09-18T02:36:00Z",
                    "completed_at": "2026-09-18T02:36:05Z",
                },
            ],
        )
    ]
    phases = {row["name"]: row for row in ci_run_timing.android_phases_from_jobs(jobs)}
    assert set(phases) == {
        "configuration", "compile", "cache_state",
        "emulator_prepare_install_test_exit", "checkout_qualification", "result_qualification",
    }
    assert phases["configuration"]["measurement_kind"] == "derived"
    assert phases["compile"]["measurement_kind"] == "direct"
    assert phases["compile"]["elapsed_s"] == 240.0
    assert phases["emulator_prepare_install_test_exit"]["measurement_kind"] == "combined"
    assert phases["checkout_qualification"]["measurement_kind"] == "direct"
    assert phases["result_qualification"]["measurement_kind"] == "direct"
    assert phases["cache_state"]["measurement_kind"] == "unknown"


def test_cancelled_run_cause_is_unknown_without_platform_evidence() -> None:
    bundle = {
        "metadata": {
            "id": 34841744593, "name": "CI", "event": "pull_request", "head_sha": "a" * 40,
            "status": "completed", "conclusion": "cancelled", "run_attempt": 1,
            "created_at": "2026-09-18T02:00:00Z",
            "pull_requests": [{"base": {"sha": "d" * 40}}],
        },
        "jobs": [
            _job(),
            _job(
                id=2, name="Android APK release", conclusion="cancelled",
                started_at="2026-09-18T02:00:00Z", completed_at="2026-09-18T02:08:00Z",
            ),
        ],
        "attempt": 1,
    }
    report = ci_run_timing.build_report([bundle], repository="xxu29958-jpg/xpj")
    assert report["cancellations"] == [{
        "run_id": 34841744593,
        "consumed_minutes": 18,
        "cause": "unknown",
        "cause_confidence": "unknown",
    }]
    assert report["runner_execution"]["by_conclusion"]["success"] == 10
    assert report["runner_execution"]["by_conclusion"]["cancelled"] == 8


def test_parse_audit_lane_timing_keeps_raw_returncode() -> None:
    text = (
        'AUDIT_LANE_TIMING {"lane":"repository-weight","filename":"_audit_repository_weight.py",'
        '"returncode":2,"started_utc":"2026-09-18T02:00:00Z","ended_utc":"2026-09-18T02:00:04Z",'
        '"elapsed_s":4.217,"elapsed_clock":"monotonic","measurement_kind":"direct","complete":true}\n'
    )
    rows = ci_run_timing.parse_audit_lane_timing(text)
    assert rows[0]["returncode"] == 2
    assert rows[0]["lane"] == "repository-weight"


def test_connected_workflow_keeps_direct_gradle_without_timing_hooks() -> None:
    workflow = ROOT / ".github" / "workflows" / "android-connected-test.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "ci-connected-inner-timing.init.gradle" not in text
    assert "Write run identity" not in text
    assert "stamp-connected-inner" not in text
    raw_line = next(
        stripped for raw in text.splitlines()
        if (stripped := raw.strip()) and ":app:connectedGrayDebugAndroidTest" in stripped
    )
    line = raw_line.removeprefix("script:").strip()
    tokens = line.split()
    assert tokens[0] == "timeout"
    assert "./gradlew" in tokens
    assert ":app:connectedGrayDebugAndroidTest" in tokens
    assert "-I" not in tokens


def test_ci_workflow_has_no_automatic_timing_job() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "name: CI run timing" not in text
    assert "Write run identity" not in text
    assert not (ROOT / ".github" / "workflows" / "ci-run-timing-observer.yml").exists()


def test_missing_required_check_list_is_incomplete() -> None:
    bundle = {
        "metadata": {
            "id": 1, "name": "CI", "event": "pull_request", "head_sha": "a" * 40,
            "status": "completed", "conclusion": "success", "run_attempt": 1,
            "created_at": "2026-09-18T02:00:00Z",
            "pull_requests": [{"base": {"sha": "d" * 40}}],
        },
        "checkout_sha": "b" * 40,
        "jobs": [_job(name="Backend")],
        "attempt": 1,
    }
    report = ci_run_timing.build_report([bundle], repository="xxu29958-jpg/xpj")
    assert report["complete"] is False
    assert "required-check set not supplied" in report["incomplete_reasons"]
    assert report["runner_execution"]["known_minutes"] == 10


def test_missing_checkout_evidence_makes_identity_incomplete() -> None:
    bundle = {
        "metadata": {
            "id": 1, "name": "CI", "event": "pull_request", "head_sha": "a" * 40,
            "status": "completed", "conclusion": "success", "run_attempt": 1,
            "created_at": "2026-09-18T02:00:00Z",
            "pull_requests": [{"base": {"sha": "d" * 40}}],
        },
        "jobs": [_job(name="Backend")],
        "attempt": 1,
    }
    report = ci_run_timing.build_report(
        [bundle],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend"],
    )
    assert report["identity_complete"] is False
    assert any("checkout" in item for item in report["incomplete_reasons"])
    assert report["complete"] is False
    assert report["runner_execution"]["known_minutes"] == 10


def test_missing_audit_evidence_when_backend_contracts_ran() -> None:
    bundle = {
        "metadata": {
            "id": 1, "name": "CI", "event": "pull_request", "head_sha": "a" * 40,
            "status": "completed", "conclusion": "success", "run_attempt": 1,
            "created_at": "2026-09-18T02:00:00Z",
            "pull_requests": [{"base": {"sha": "d" * 40}}],
        },
        "checkout_sha": "b" * 40,
        "jobs": [_job(name="Backend contracts")],
        "attempt": 1,
    }
    report = ci_run_timing.build_report(
        [bundle],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts"],
    )
    assert report["complete"] is False
    assert "audit lane timing unavailable" in report["incomplete_reasons"]
    assert report["runner_execution"]["known_minutes"] == 10


def _rerun_jobs() -> tuple[list[dict], list[dict]]:
    first = [
        _job(
            id=10, name="CI scope",
            started_at="2026-09-18T02:52:23Z", completed_at="2026-09-18T02:52:32Z",
            created_at="2026-09-18T02:52:20Z",
        ),
        _job(id=11, name="Backend contracts", started_at="2026-09-18T02:53:00Z", completed_at="2026-09-18T03:00:00Z"),
        _job(id=12, name="Android", started_at="2026-09-18T02:53:00Z", completed_at="2026-09-18T03:02:00Z"),
        _job(
            id=13, name="Windows installer build", labels=["windows-latest"],
            started_at="2026-09-18T02:53:00Z", completed_at="2026-09-18T03:08:00Z",
        ),
        _job(
            id=14, name="Failing lane", conclusion="failure",
            started_at="2026-09-18T02:53:00Z", completed_at="2026-09-18T03:03:00Z",
        ),
    ]
    inherited = [
        {**job, "id": int(job["id"]) + 100, "run_attempt": 2, "created_at": "2026-09-18T03:35:00Z"}
        for job in first[:-1]
    ]
    rerun = _job(
        id=114, name="Failing lane", run_attempt=2,
        started_at="2026-09-18T03:36:00Z", completed_at="2026-09-18T03:41:00Z",
        created_at="2026-09-18T03:35:00Z",
    )
    return first, inherited + [rerun]


def test_attempt_one_and_two_sum_unique_actual_execution() -> None:
    first, second = _rerun_jobs()
    report = ci_run_timing.build_report(
        [{
            "metadata": {
                "id": 35301042897, "name": "CI", "event": "pull_request", "head_sha": "a" * 40,
                "status": "completed", "conclusion": "success", "run_attempt": 2,
                "created_at": "2026-09-18T02:52:00Z", "run_started_at": "2026-09-18T02:52:05Z",
                "pull_requests": [{"base": {"sha": "d" * 40}}],
            },
            "checkout_sha": "b" * 40,
            "attempts": [{"attempt": 1, "jobs": first}, {"attempt": 2, "jobs": second}],
        }],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts", "Android"],
        audit_lanes=[_audit_lane()],
        audit_run=_audit_run(),
    )
    workflow = report["workflows"][0]
    assert workflow["attempts"][0]["actual_execution_minutes"] == 41.15
    assert workflow["attempts"][0]["inherited_job_count"] == 0
    assert workflow["attempts"][0]["execution_state"] == "completed"
    assert workflow["attempts"][0]["measurement_kind"] == "derived_from_jobs"
    assert workflow["attempts"][0]["first_actual_job_started_at"] is not None
    assert workflow["attempts"][1]["actual_execution_minutes"] == 5
    assert workflow["attempts"][1]["inherited_job_count"] == 4
    assert workflow["attempts"][1]["first_actual_job_started_at"].startswith("2026-09-18T03:36:00")
    assert workflow["attempts"][1]["last_actual_job_completed_at"].startswith("2026-09-18T03:41:00")
    assert report["runner_execution"]["known_minutes"] == 46.15
    assert workflow["runner_execution_minutes"] == 46.15
    assert report["complete"] is True


def test_malformed_audit_log_preserves_runner_totals(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({
        "checkout_sha": "b" * 40,
        "jobs": [_job(name="Backend contracts")],
    }), encoding="utf-8")
    audit = tmp_path / "audit.log"
    audit.write_text("AUDIT_LANE_TIMING {not-json}\n", encoding="utf-8")
    output = tmp_path / "timing.json"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "ci_run_timing.py"),
            "--jobs-json", str(jobs), "--attempt", "1",
            "--workflow-name", "CI", "--event", "pull_request",
            "--source-sha", "a" * 40, "--base-sha", "d" * 40,
            "--required-check", "Backend contracts",
            "--audit-log", str(audit),
            "--output-json", str(output),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == 2
    assert payload["runner_execution"]["known_minutes"] == 10
    assert payload["complete"] is False
    assert any("audit" in item for item in payload["incomplete_reasons"])


def test_remote_mode_fetches_all_attempts_and_scope_logs() -> None:
    first, second = _rerun_jobs()
    first[0] = {**first[0], "name": "CI scope"}
    log_text = (
        "\ufeff2026-09-19T10:42:32.1076787Z "
        f"Qualification checkout SHA: {'b' * 40}; source SHA: {'a' * 40}\r\n"
        "2026-09-19T10:42:32.1076787Z "
        'AUDIT_LANE_TIMING {"lane":"repository-weight","filename":"_audit_repository_weight.py",'
        '"returncode":0,"complete":true}\r\n'
        "2026-09-19T10:42:32.2076787Z "
        'AUDIT_RUN_TIMING {"expected_lanes":["repository-weight"],"expected_lane_count":1,'
        '"completed_lane_count":1,"overall_returncode":0,"complete":true}\r\n'
    )

    def opener(request):
        url = request.full_url
        if url.endswith("/actions/runs/35301042897"):
            return _FakeResponse({
                "id": 35301042897, "name": "CI", "event": "pull_request", "head_sha": "a" * 40,
                "status": "completed", "conclusion": "success", "run_attempt": 2,
                "created_at": "2026-09-18T02:52:00Z", "run_started_at": "2026-09-18T02:52:05Z",
                "pull_requests": [{"base": {"sha": "d" * 40}}],
            })
        if "/attempts/1/jobs" in url:
            return _FakeResponse({"jobs": first})
        if "/attempts/2/jobs" in url:
            return _FakeResponse({"jobs": second})
        if url.endswith("/logs"):
            return _FakeResponse(log_text.encode("utf-8"))
        raise AssertionError(url)

    args = SimpleNamespace(
        run_ids=[35301042897], repository="xxu29958-jpg/xpj", jobs_json=None,
        audit_log=[], qualification_log=[], required_check=["Backend contracts", "Android"],
        output_json=None, summary=None, workflow_name=None, event=None, source_sha=None,
        base_sha=None, run_conclusion=None, attempt=None, previous_jobs_json=None,
    )
    with patch.dict(os.environ, {"GITHUB_TOKEN": "t"}, clear=False), patch.object(ci_run_timing.urllib.request, "urlopen", opener):
        bundles = ci_run_timing._load_remote_bundles(args)
        qualification, audit_lanes, audit_run, errors = ci_run_timing.attach_remote_evidence(
            bundles, "xxu29958-jpg/xpj", "t", urlopen=opener,
        )
    assert [item["attempt"] for item in bundles[0]["attempts"]] == [1, 2]
    assert qualification[0][0] == "b" * 40
    assert audit_lanes[0]["returncode"] == 0
    assert audit_run is not None
    assert audit_run["complete"] is True
    report = ci_run_timing.build_report(
        bundles,
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts", "Android"],
        audit_lanes=audit_lanes,
        qualification=qualification,
        audit_run=audit_run,
        evidence_errors=errors,
    )
    assert report["runner_execution"]["known_minutes"] == 46.15
    assert report["identity_complete"] is True
    assert report["complete"] is True


def _finished_ci(
    *,
    run_id: int = 1,
    name: str = "CI",
    event: str = "pull_request",
    head: str = "a" * 40,
    checkout: str = "c" * 40,
    base: str | None = "d" * 40,
    jobs: list[dict] | None = None,
    attempt: int = 1,
    created_at: str = "2026-09-18T02:00:00Z",
    run_started_at: str | None = "2026-09-18T02:00:05Z",
    attempts: list[dict] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "id": run_id,
        "name": name,
        "event": event,
        "head_sha": head,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": attempt,
        "created_at": created_at,
    }
    if run_started_at is not None:
        metadata["run_started_at"] = run_started_at
    if base:
        metadata["pull_requests"] = [{"base": {"sha": base}}]
    bundle: dict[str, object] = {
        "metadata": metadata,
        "checkout_sha": checkout,
        "attempt": attempt,
    }
    if attempts is not None:
        bundle["attempts"] = attempts
    else:
        bundle["jobs"] = jobs if jobs is not None else [_job(name="Backend", head_sha=head, run_id=run_id)]
    return bundle


def test_parse_audit_lane_timing_reads_github_prefixed_bom_crlf() -> None:
    text = (
        "\ufeff2026-09-19T10:42:32.1076787Z "
        'AUDIT_LANE_TIMING {"lane":"repository-weight","filename":"_audit_repository_weight.py",'
        '"returncode":0,"started_utc":"2026-09-19T10:42:28Z","ended_utc":"2026-09-19T10:42:32Z",'
        '"elapsed_s":4.1,"elapsed_clock":"monotonic","measurement_kind":"direct","complete":true}\r\n'
        "2026-09-19T10:42:32.2076787Z "
        'AUDIT_RUN_TIMING {"expected_lanes":["repository-weight"],"expected_lane_count":1,'
        '"completed_lane_count":1,"overall_returncode":0,"complete":true}\r\n'
    )
    rows = ci_run_timing.parse_audit_lane_timing(text)
    assert rows[0]["lane"] == "repository-weight"
    assert rows[0]["returncode"] == 0
    run = ci_run_timing.parse_audit_run_timing(text)
    assert run is not None
    assert run["expected_lane_count"] == 1
    assert run["complete"] is True


def test_partial_audit_log_without_run_marker_is_incomplete() -> None:
    report = ci_run_timing.build_report(
        [_finished_ci(jobs=[_job(name="Backend contracts")], checkout="b" * 40)],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts"],
        audit_lanes=[_audit_lane()],
    )
    assert report["complete"] is False
    assert "audit lane timing unavailable" in report["incomplete_reasons"]
    assert report["runner_execution"]["known_minutes"] == 10


def test_duplicate_and_missing_audit_lanes_are_incomplete() -> None:
    report = ci_run_timing.build_report(
        [_finished_ci(jobs=[_job(name="Backend contracts")], checkout="b" * 40)],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts"],
        audit_lanes=[_audit_lane("codebase"), _audit_lane("codebase")],
        audit_run=_audit_run(["codebase", "repository-weight", "ci-gap"]),
    )
    assert report["complete"] is False
    assert any("duplicate audit lanes" in item for item in report["incomplete_reasons"])
    assert any("missing audit lanes" in item for item in report["incomplete_reasons"])


def test_qualification_source_mismatch_fails_identity() -> None:
    report = ci_run_timing.build_report(
        [_finished_ci(head="a" * 40, checkout="c" * 40)],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend"],
        qualification=[("c" * 40, "b" * 40)],
    )
    assert report["identity_complete"] is False
    assert any("qualification source mismatch: " in item for item in report["incomplete_reasons"])
    assert report["complete"] is False


def test_mixed_pull_request_and_push_events_fail_identity() -> None:
    report = ci_run_timing.build_report(
        [
            _finished_ci(run_id=1, event="pull_request"),
            _finished_ci(run_id=2, name="CodeQL", event="push", jobs=[_job(id=2, name="CodeQL", run_id=2)]),
        ],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend", "CodeQL"],
    )
    assert report["identity_complete"] is False
    assert "mixed event" in report["incomplete_reasons"]
    assert report["complete"] is False


def test_mixed_checkout_sha_fails_identity() -> None:
    report = ci_run_timing.build_report(
        [_finished_ci(head="a" * 40, checkout="c" * 40)],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend"],
        qualification=[("e" * 40, "a" * 40)],
    )
    assert report["identity_complete"] is False
    assert "mixed checkout SHA" in report["incomplete_reasons"]
    assert report["complete"] is False


def test_mixed_base_sha_fails_identity() -> None:
    report = ci_run_timing.build_report(
        [
            _finished_ci(run_id=1, base="d" * 40),
            _finished_ci(run_id=2, name="CodeQL", base="e" * 40, jobs=[_job(id=2, name="CodeQL", run_id=2)]),
        ],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend", "CodeQL"],
    )
    assert report["identity_complete"] is False
    assert "mixed base_sha" in report["incomplete_reasons"]
    assert report["complete"] is False


def test_missing_attempt_keeps_minutes_but_runner_incomplete() -> None:
    report = ci_run_timing.build_report(
        [_finished_ci(
            attempt=2,
            jobs=None,
            attempts=[{"attempt": 1, "jobs": [_job()]}],
        )],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts"],
        audit_lanes=[_audit_lane()],
        audit_run=_audit_run(),
    )
    assert report["runner_execution"]["known_minutes"] == 10
    assert report["runner_execution"]["complete"] is False
    assert report["runner_execution"]["known_partial"] is True
    assert report["workflows"][0]["complete"] is False
    assert report["complete"] is False
    assert any("missing attempt 2 jobs for CI" in item for item in report["incomplete_reasons"])


def test_corrupt_zip_keeps_measured_subset() -> None:
    first, second = _rerun_jobs()
    bundles = [_finished_ci(
        run_id=35301042897,
        checkout="b" * 40,
        attempt=2,
        created_at="2026-09-18T02:52:00Z",
        run_started_at="2026-09-18T02:52:05Z",
        attempts=[{"attempt": 1, "jobs": first}, {"attempt": 2, "jobs": second}],
    )]

    def opener(request):
        if request.full_url.endswith("/logs"):
            return _FakeResponse(b"PK\x03\x04not-a-zip-file")
        raise AssertionError(request.full_url)

    assert zipfile.BadZipFile in ci_run_timing._LOAD_CATCH
    assert zipfile.LargeZipFile in ci_run_timing._LOAD_CATCH
    qualification, audit_lanes, audit_run, errors = ci_run_timing.attach_remote_evidence(
        bundles, "xxu29958-jpg/xpj", "t", urlopen=opener,
    )
    assert qualification == []
    assert audit_lanes == []
    assert audit_run is None
    assert errors
    report = ci_run_timing.build_report(
        bundles,
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts", "Android"],
        audit_lanes=audit_lanes,
        qualification=qualification,
        audit_run=audit_run,
        evidence_errors=errors,
    )
    assert report["runner_execution"]["known_minutes"] == 46.15
    assert report["complete"] is False


def test_android_attempt_two_rerun_uses_latest_phase_evidence() -> None:
    first = _job(
        name="Connected execution",
        workflow_name="Android Connected Test",
        steps=_connected_steps(run_started="2026-09-18T02:15:00Z", run_ended="2026-09-18T02:35:00Z"),
    )
    rerun = _job(
        id=2,
        name="Connected execution",
        workflow_name="Android Connected Test",
        run_attempt=2,
        started_at="2026-09-18T03:36:00Z",
        completed_at="2026-09-18T04:00:00Z",
        steps=_connected_steps(run_started="2026-09-18T03:40:00Z", run_ended="2026-09-18T03:55:00Z"),
    )
    phases = {row["name"]: row for row in ci_run_timing.android_phases_from_attempts([
        {"attempt": 1, "jobs": [first]},
        {"attempt": 2, "jobs": [rerun]},
    ])}
    row = phases["emulator_prepare_install_test_exit"]
    assert row["attempt"] == 2
    assert row["evidence_attempt"] == 2
    assert row["inherited"] is False
    assert row["measurement_kind"] == "combined"
    assert row["elapsed_s"] == 900.0


def test_android_inherited_phase_keeps_prior_evidence_attempt() -> None:
    first = _job(
        name="Connected execution",
        workflow_name="Android Connected Test",
        steps=_connected_steps(run_started="2026-09-18T02:15:00Z", run_ended="2026-09-18T02:35:00Z"),
    )
    inherited = {**first, "id": 99, "run_attempt": 2, "created_at": "2026-09-18T03:35:00Z"}
    phases = {row["name"]: row for row in ci_run_timing.android_phases_from_attempts([
        {"attempt": 1, "jobs": [first]},
        {"attempt": 2, "jobs": [inherited]},
    ])}
    row = phases["emulator_prepare_install_test_exit"]
    assert row["attempt"] == 2
    assert row["evidence_attempt"] == 1
    assert row["inherited"] is True
    assert row["elapsed_s"] == 1200.0


def test_inherited_only_attempt_has_null_times() -> None:
    first, second = _rerun_jobs()
    report = ci_run_timing.build_report(
        [_finished_ci(
            run_id=35301042897,
            checkout="b" * 40,
            attempt=2,
            created_at="2026-09-18T02:52:00Z",
            run_started_at="2026-09-18T02:52:05Z",
            attempts=[{"attempt": 1, "jobs": first}, {"attempt": 2, "jobs": second[:-1]}],
        )],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts", "Android"],
        audit_lanes=[_audit_lane()],
        audit_run=_audit_run(),
    )
    row = report["workflows"][0]["attempts"][1]
    assert row["execution_state"] == "inherited_only"
    assert row["first_actual_job_started_at"] is None
    assert row["last_actual_job_completed_at"] is None
    assert row["actual_execution_minutes"] == 0
    assert row["measurement_kind"] == "derived_from_jobs"


def test_missing_run_started_at_makes_wait_incomplete() -> None:
    report = ci_run_timing.build_report(
        [_finished_ci(run_started_at=None)],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend"],
    )
    wait = report["required_gate_wait"]
    assert wait["complete"] is False
    assert wait["first_workflow_started_at"] is None
    assert wait["trigger_created_at"] is not None
    assert wait["required_checks"] == ["Backend"]
    assert wait["required_check_source"] == "explicit_cli"
    assert any("run_started_at" in item for item in report["incomplete_reasons"])
    assert report["complete"] is False


def test_inverted_gate_times_keep_original_and_fail_complete() -> None:
    report = ci_run_timing.build_report(
        [_finished_ci(
            created_at="2026-09-18T02:00:00Z",
            run_started_at="2026-09-18T02:50:00Z",
            jobs=[_job(name="Backend", started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:40:00Z")],
        )],
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend"],
    )
    wait = report["required_gate_wait"]
    assert wait["complete"] is False
    assert wait["trigger_created_at"].startswith("2026-09-18T02:00:00")
    assert wait["first_workflow_started_at"].startswith("2026-09-18T02:50:00")
    assert wait["last_required_check_completed_at"].startswith("2026-09-18T02:40:00")
    assert wait["required_checks"] == ["Backend"]
    assert wait["required_check_source"] == "explicit_cli"
    assert any("inverted required-gate wait timestamps" in item for item in report["incomplete_reasons"])
    assert report["complete"] is False


from __future__ import annotations

import json
import os
import subprocess
import sys
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
        audit_lanes=[{
            "lane": "repository-weight", "filename": "_audit_repository_weight.py",
            "returncode": 0, "complete": True,
        }],
    )
    workflow = report["workflows"][0]
    assert workflow["attempts"][0]["actual_execution_minutes"] == 41.15
    assert workflow["attempts"][0]["inherited_job_count"] == 0
    assert workflow["attempts"][1]["actual_execution_minutes"] == 5
    assert workflow["attempts"][1]["inherited_job_count"] == 4
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
    log_text = f"Qualification checkout SHA: {'b' * 40}; source SHA: {'a' * 40}\n"
    log_text += (
        'AUDIT_LANE_TIMING {"lane":"repository-weight","filename":"_audit_repository_weight.py",'
        '"returncode":0,"complete":true}\n'
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
        qualification, audit_lanes, errors = ci_run_timing.attach_remote_evidence(
            bundles, "xxu29958-jpg/xpj", "t", urlopen=opener,
        )
    assert [item["attempt"] for item in bundles[0]["attempts"]] == [1, 2]
    assert qualification[0][0] == "b" * 40
    assert audit_lanes[0]["returncode"] == 0
    report = ci_run_timing.build_report(
        bundles,
        repository="xxu29958-jpg/xpj",
        required_checks=["Backend contracts", "Android"],
        audit_lanes=audit_lanes,
        qualification=qualification,
        evidence_errors=errors,
    )
    assert report["runner_execution"]["known_minutes"] == 46.15
    assert report["identity_complete"] is True
    assert report["complete"] is True


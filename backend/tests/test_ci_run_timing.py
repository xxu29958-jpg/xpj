from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import ci_run_timing

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


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
    latest = {
        **first,
        "run_attempt": 2,
        "created_at": "2026-09-18T03:35:00Z",
    }
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
    inherited = {
        **first,
        "id": 105471586858,
        "run_attempt": 2,
        "created_at": "2026-09-18T03:35:00Z",
    }
    summary = ci_run_timing.summarize_jobs([inherited], attempt=2, previous_jobs=[first])
    assert summary["jobs"][0]["id"] == 105471586858
    assert summary["jobs"][0]["inherited"] is True
    assert summary["jobs"][0]["queue_s"] is None
    assert summary["jobs"][0]["queue_status"] == "created_after_start"
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is True


def test_attempt_two_without_previous_evidence_is_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs([_job(run_attempt=2)], attempt=2)
    assert summary["complete"] is False
    assert summary["runner_execution_minutes"] == 0
    assert any("previous-attempt evidence" in item for item in summary["incomplete"])


def test_timed_out_execution_is_counted_and_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(
            conclusion="timed_out",
            started_at="2026-09-18T02:00:00Z",
            completed_at="2026-09-18T02:10:00Z",
        )],
        attempt=1,
    )
    assert summary["other_execution_minutes"] == 10
    assert summary["total_execution_minutes"] == 10
    assert summary["runner_execution_minutes"] == 10
    assert summary["complete"] is False
    assert any("unsupported" in item for item in summary["incomplete"])


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
    assert summary["run_id"] is None
    assert summary["head_sha"] is None
    assert summary["workflow_name"] is None
    assert summary["runner_execution_minutes"] == 0
    assert any("missing shared" in item for item in summary["incomplete"])


def test_missing_run_attempt_is_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(run_attempt=None)],
        attempt=1,
    )
    assert summary["complete"] is False
    assert any("run_attempt" in item for item in summary["incomplete"])


def test_successful_step_without_timestamps_is_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(steps=[{
            "name": "Audit",
            "conclusion": "success",
            "started_at": None,
            "completed_at": None,
        }])],
        attempt=1,
    )
    assert summary["complete"] is False
    assert summary["step_timing_complete"] is False
    assert summary["runner_execution_minutes"] == 10
    assert summary["total_execution_minutes"] == 10
    assert summary["success_execution_minutes"] == 10
    assert any("executed step missing timestamps" in item for item in summary["incomplete"])


def test_inverted_timestamps_are_incomplete_not_silently_zeroed() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(
            started_at="2026-09-18T04:00:00Z",
            completed_at="2026-09-18T03:00:00Z",
        )],
        attempt=1,
    )
    assert summary["jobs"][0]["inverted"] is True
    assert summary["jobs"][0]["execution_s"] is None
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False


def test_cancelled_consumed_time_is_listed_separately() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(
            name="Android",
            conclusion="cancelled",
            started_at="2026-09-18T02:00:00Z",
            completed_at="2026-09-18T02:10:00Z",
        )],
        attempt=1,
    )
    assert summary["cancelled_consumed_minutes"] == 10
    assert summary["cancelled_execution_minutes"] == 10
    assert summary["runner_execution_minutes"] == 10
    assert summary["complete"] is True


def test_cli_reads_fixture_jobs(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job(
        id=4,
        name="Connected",
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
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "ci_run_timing.py"), "--jobs-json", str(jobs), "--attempt", "1"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "runner_execution_minutes=" in result.stdout
    assert "Connected" in result.stdout
    assert "queue_s=" in result.stdout
    assert "step Run connected test" in result.stdout
    assert "elapsed_s=" in result.stdout


def test_attempt_mismatch_contributes_zero_current_attempt_minutes() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(run_attempt=1, started_at="2026-09-18T02:00:00Z", completed_at="2026-09-18T02:10:00Z")],
        attempt=2,
        previous_jobs=[],
    )
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False
    assert any("previous-attempt evidence" in item or "attempt mismatch" in item for item in summary["incomplete"])


def test_mixed_run_id_or_head_sha_is_incomplete() -> None:
    mixed_run = ci_run_timing.summarize_jobs(
        [_job(run_id=1), _job(id=2, name="Android", run_id=2)],
        attempt=1,
    )
    assert mixed_run["complete"] is False
    assert mixed_run["runner_execution_minutes"] == 0
    mixed_sha = ci_run_timing.summarize_jobs(
        [_job(), _job(id=2, name="Android", head_sha="b" * 40)],
        attempt=1,
    )
    assert mixed_sha["complete"] is False


def test_failed_cancelled_and_skipped_totals_are_distinct() -> None:
    summary = ci_run_timing.summarize_jobs(
        [
            _job(id=1, name="ok", conclusion="success"),
            _job(
                id=2, name="bad", conclusion="failure",
                started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:06:00Z",
            ),
            _job(
                id=3, name="stop", conclusion="cancelled",
                started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:04:00Z",
            ),
            _job(id=4, name="skip", conclusion="skipped", started_at=None, completed_at=None),
        ],
        attempt=1,
    )
    assert summary["success_execution_minutes"] == 10
    assert summary["failure_execution_minutes"] == 5
    assert summary["cancelled_consumed_minutes"] == 3
    assert summary["skipped_jobs"] == ["skip"]
    assert summary["complete"] is True
    assert not any("missing execution interval" in item for item in summary["incomplete"])


def test_rendered_output_includes_queue_and_step_timing() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(steps=[{
            "name": "Audit",
            "conclusion": "success",
            "started_at": "2026-09-18T02:02:00Z",
            "completed_at": "2026-09-18T02:09:00Z",
        }])],
        attempt=1,
    )
    rendered = ci_run_timing.render_timing(summary)
    assert "queue_s=60.0" in rendered
    assert "step Audit" in rendered
    assert "elapsed_s=420.0" in rendered
    assert "observed_subset_wall_clock_s=" in rendered
    assert "not the final required-check wait" in rendered


def test_step_inversion_is_incomplete_and_not_billed() -> None:
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
    assert summary["success_execution_minutes"] == 10
    assert any("inverted step" in item for item in summary["incomplete"])


def test_negative_created_to_started_is_not_queue_time() -> None:
    rendered = ci_run_timing.render_timing(
        ci_run_timing.summarize_jobs(
            [_job(created_at="2026-09-18T03:35:00Z", started_at="2026-09-18T02:52:23Z")],
            attempt=1,
        )
    )
    assert "queue_s=None" in rendered
    assert "created_after_start" in rendered
    assert "queue_s=-" not in rendered


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

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


def test_exclude_observer_job_can_be_complete() -> None:
    observer = _job(
        name="CI run timing",
        conclusion=None,
        status="in_progress",
        completed_at=None,
        started_at="2026-09-19T06:42:40Z",
    )
    summary = ci_run_timing.summarize_jobs(
        [_job(), observer],
        attempt=1,
        exclude_job_names=("CI run timing",),
        report_identity={
            "repository": "xxu29958-jpg/xpj",
            "workflow": "CI",
            "run_id": 100,
            "run_attempt": 1,
            "event": "pull_request",
            "source_sha": "a" * 40,
            "measurement_sha": "b" * 40,
        },
    )
    assert summary["complete"] is True
    assert summary["coverage_exclusions"] == ["CI run timing observer itself"]
    assert summary["runner_execution_minutes"] == 10
    assert [job["name"] for job in summary["jobs"]] == ["Backend contracts"]
    assert summary["identity"]["source_sha"] == "a" * 40
    assert summary["identity"]["measurement_sha"] == "b" * 40


def test_cancelled_jobs_are_billed_and_remain_visible() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(
            name="Android fast",
            conclusion="cancelled",
            started_at="2026-09-18T02:00:00Z",
            completed_at="2026-09-18T02:07:00Z",
        )],
        attempt=1,
    )
    assert summary["cancelled_execution_minutes"] == 7
    assert summary["total_execution_minutes"] == 7
    assert summary["complete"] is True


def test_cli_excludes_observer_and_persists_identity(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [
        _job(),
        _job(id=99, name="CI run timing", conclusion=None, status="in_progress", completed_at=None),
    ]}), encoding="utf-8")
    output = tmp_path / "timing.json"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "ci_run_timing.py"),
            "--jobs-json", str(jobs), "--attempt", "1",
            "--exclude-job-name", "CI run timing",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "100",
            "--workflow-name", "CI",
            "--event", "pull_request",
            "--source-sha", "a" * 40,
            "--measurement-sha", "b" * 40,
            "--output-json", str(output),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["complete"] is True
    assert payload["coverage_exclusions"] == ["CI run timing observer itself"]
    assert payload["identity"]["source_sha"] == "a" * 40
    assert payload["identity"]["measurement_sha"] == "b" * 40
    assert payload["identity"]["run_id"] in {100, "100"}


def test_stamp_connected_inner_adds_identity(tmp_path: Path) -> None:
    inner = tmp_path / "connected-inner-timing.json"
    inner.write_text(json.dumps({
        "kind": "gradle_connected_test",
        "elapsed_s": 976.03,
        "gradle_failure": False,
    }), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "ci_run_timing.py"),
            "--stamp-connected-inner", str(inner),
            "--attempt", "1",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "35426715230",
            "--workflow-name", "Android Connected Test",
            "--event", "pull_request",
            "--source-sha", "a" * 40,
            "--measurement-sha", "b" * 40,
            "--job-name", "Connected execution",
            "--outer-step", "Run connected test",
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(inner.read_text(encoding="utf-8"))
    assert payload["complete"] is True
    assert payload["elapsed_s"] == 976.03
    assert payload["job"] == "Connected execution"
    assert payload["outer_step"] == "Run connected test"
    assert payload["identity"]["source_sha"] == "a" * 40
    assert payload["identity"]["run_id"] in {35426715230, "35426715230"}


def test_live_merge_ref_uses_singular_pull_path_and_does_not_adopt_stale_sha() -> None:
    calls: list[str] = []

    def opener(request):
        calls.append(request.full_url)
        if "/git/ref/pulls/" in request.full_url:
            raise AssertionError(request.full_url)
        if request.full_url.endswith("/git/ref/pull/420/merge"):
            return _FakeResponse({"object": {"sha": "c" * 40}})
        if "/git/commits/" in request.full_url:
            return _FakeResponse({"parents": [{"sha": "e" * 40}, {"sha": "f" * 40}]})
        raise AssertionError(request.full_url)

    status = ci_run_timing.cross_check_live_merge_ref(
        "xxu29958-jpg/xpj",
        420,
        {"source_sha": "a" * 40, "base_sha": "d" * 40},
        "token",
        urlopen=opener,
    )
    assert status == "stale_or_mismatch"
    assert any(url.endswith("/git/ref/pull/420/merge") for url in calls)


def test_parse_qualification_log_reads_authoritative_line() -> None:
    parsed = ci_run_timing.parse_qualification_log(
        "Qualification checkout SHA: " + "b" * 40 + "; source SHA: " + "a" * 40 + "\n"
    )
    assert parsed == ("b" * 40, "a" * 40)


def test_previous_mixed_identity_does_not_bill_current_attempt() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(id=3, run_attempt=2, started_at="2026-09-18T03:00:00Z", completed_at="2026-09-18T03:10:00Z")],
        attempt=2,
        previous_jobs=[_job(run_attempt=1), _job(id=2, name="Android", run_id=999, run_attempt=1)],
    )
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False


def test_previous_wrong_head_does_not_bill_current_attempt() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(id=3, run_attempt=2, started_at="2026-09-18T03:00:00Z", completed_at="2026-09-18T03:10:00Z")],
        attempt=2,
        previous_jobs=[_job(run_attempt=1, head_sha="b" * 40)],
    )
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False


def test_previous_attempt_not_older_does_not_bill() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(id=3, run_attempt=2, started_at="2026-09-18T03:00:00Z", completed_at="2026-09-18T03:10:00Z")],
        attempt=2,
        previous_jobs=[_job(run_attempt=2)],
    )
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False


def test_identity_run_id_mismatch_keeps_job_cost_and_is_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job()],
        attempt=1,
        report_identity={
            "repository": "xxu29958-jpg/xpj",
            "workflow": "CI",
            "run_id": 999,
            "run_attempt": 1,
            "event": "pull_request",
            "source_sha": "a" * 40,
            "measurement_sha": "b" * 40,
        },
    )
    assert summary["runner_execution_minutes"] == 10
    assert summary["complete"] is False
    assert summary["identity_complete"] is False
    assert any("run_id" in item for item in summary["incomplete"])


def test_cancelled_run_without_distinct_measurement_still_writes_cost(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [
        _job(),
        _job(
            id=2,
            name="Android APK release",
            conclusion="cancelled",
            started_at="2026-09-18T02:00:00Z",
            completed_at="2026-09-18T02:08:00Z",
        ),
    ]}), encoding="utf-8")
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({
        "repository": "xxu29958-jpg/xpj",
        "workflow": "CI",
        "run_id": 100,
        "run_attempt": 1,
        "event": "pull_request",
        "source_sha": "a" * 40,
        "measurement_sha": "a" * 40,
    }), encoding="utf-8")
    output = tmp_path / "timing.json"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "ci_run_timing.py"),
            "--jobs-json", str(jobs), "--attempt", "1",
            "--run-identity-json", str(identity),
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "100",
            "--workflow-name", "CI",
            "--event", "pull_request",
            "--source-sha", "a" * 40,
            "--measurement-sha", "a" * 40,
            "--output-json", str(output),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["cancelled_execution_minutes"] == 8
    assert payload["success_execution_minutes"] == 10
    assert payload["complete"] is False
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
    assert payload["reason"]


def test_write_scope_identity_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "ci-run-identity.json"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "ci_run_timing.py"),
            "--write-identity-json", str(path),
            "--attempt", "1",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "100",
            "--workflow-name", "CI",
            "--event", "pull_request",
            "--source-sha", "a" * 40,
            "--measurement-sha", "b" * 40,
            "--base-sha", "d" * 40,
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source_sha"] == "a" * 40
    assert payload["measurement_sha"] == "b" * 40
    assert payload["base_sha"] == "d" * 40


def test_stamp_connected_inner_missing_elapsed_is_incomplete(tmp_path: Path) -> None:
    inner = tmp_path / "connected-inner-timing.json"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "ci_run_timing.py"),
            "--stamp-connected-inner", str(inner),
            "--attempt", "1",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "1",
            "--workflow-name", "Android Connected Test",
            "--event", "pull_request",
            "--source-sha", "a" * 40,
            "--measurement-sha", "b" * 40,
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0
    payload = json.loads(inner.read_text(encoding="utf-8"))
    assert payload["complete"] is False
    assert payload["state"] == "started"
    assert "not finalized" in str(payload["reason"])


def test_connected_workflow_keeps_direct_gradle_and_inner_timing() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "android-connected-test.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "ci-connected-inner-timing.init.gradle" in text
    raw_line = next(
        stripped for raw in text.splitlines()
        if (stripped := raw.strip()) and ":app:connectedGrayDebugAndroidTest" in stripped
    )
    line = raw_line.removeprefix("script:").strip()
    tokens = line.split()
    assert tokens[0] == "timeout"
    assert "./gradlew" in tokens
    assert ":app:connectedGrayDebugAndroidTest" in tokens
    assert "-I" in tokens
    assert "ci-connected-inner-timing.init.gradle" in tokens

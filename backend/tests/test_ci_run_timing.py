from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

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
            "base_sha": "d" * 40,
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
            "--base-sha", "d" * 40,
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
    assert payload["identity"]["base_sha"] == "d" * 40
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
            "base_sha": "d" * 40,
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
        "base_sha": "d" * 40,
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
    assert result.returncode == 2
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
    _, _, after_start = text.partition("Start inner connected command timing")
    start_block, _, after_stamp = after_start.partition("Stamp inner connected command timing")
    stamp_block, _, _upload = after_stamp.partition("Upload inner connected command timing")
    assert "--allow-partial" in start_block
    assert "--inner-state started" in start_block
    assert "--allow-partial" not in stamp_block


def _pr_identity(**fields: object) -> dict[str, object]:
    row: dict[str, object] = {
        "repository": "xxu29958-jpg/xpj",
        "workflow": "CI",
        "run_id": 100,
        "run_attempt": 1,
        "event": "pull_request",
        "base_sha": "d" * 40,
        "source_sha": "a" * 40,
        "measurement_sha": "b" * 40,
    }
    row.update(fields)
    return row


def _zip_json(payload: dict, name: str = "ci-run-identity.json") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, json.dumps(payload))
    return buffer.getvalue()


def _main(argv: list[str], env: dict[str, str], urlopen) -> int:
    with (
        patch.object(sys, "argv", ["ci_run_timing.py", *argv]),
        patch.dict(os.environ, env, clear=False),
        patch.object(ci_run_timing.urllib.request, "urlopen", urlopen),
    ):
        return ci_run_timing.main()


def _identity_listing(*downloads: tuple[str, str]) -> dict:
    return {
        "artifacts": [
            {
                "name": name,
                "expired": False,
                "archive_download_url": url,
            }
            for name, url in downloads
        ]
    }


def _timing_argv(jobs: Path, output: Path, extra: list[str]) -> list[str]:
    return [
        "--jobs-json", str(jobs), "--attempt", "1",
        "--from-run-identity",
        "--github-repository", "xxu29958-jpg/xpj",
        "--github-run-id", "100",
        "--event", "pull_request",
        "--output-json", str(output),
        *extra,
    ]


def test_from_run_identity_missing_artifact_keeps_cost(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job()]}), encoding="utf-8")
    output = tmp_path / "timing.json"

    def opener(request):
        if "artifacts?per_page=100" in request.full_url:
            return _FakeResponse({"artifacts": []})
        raise AssertionError(request.full_url)

    code = _main(
        _timing_argv(jobs, output, []),
        {"GITHUB_TOKEN": "t", "GITHUB_SHA": "f" * 40},
        opener,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 2
    assert payload["success_execution_minutes"] == 10
    assert payload["complete"] is False
    assert payload["identity_complete"] is False
    assert payload["reason"] == ci_run_timing.IDENTITY_UNAVAILABLE
    assert payload["identity"]["measurement_sha"] is None


def test_from_run_identity_download_failure_keeps_cost(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job()]}), encoding="utf-8")
    output = tmp_path / "timing.json"

    def opener(request):
        if "artifacts?per_page=100" in request.full_url:
            return _FakeResponse(_identity_listing((ci_run_timing.IDENTITY_ARTIFACT, "https://api.github.com/download/identity")))
        if request.full_url == "https://api.github.com/download/identity":
            raise urllib.error.URLError("download failed")
        raise AssertionError(request.full_url)

    code = _main(
        _timing_argv(jobs, output, []),
        {"GITHUB_TOKEN": "t", "GITHUB_SHA": "f" * 40},
        opener,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 2
    assert payload["success_execution_minutes"] == 10
    assert payload["reason"] == ci_run_timing.IDENTITY_UNAVAILABLE
    assert payload["identity"]["measurement_sha"] is None


def test_from_run_identity_large_zip_keeps_cost(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job()]}), encoding="utf-8")
    output = tmp_path / "timing.json"

    def opener(request):
        if "artifacts?per_page=100" in request.full_url:
            return _FakeResponse(_identity_listing((ci_run_timing.IDENTITY_ARTIFACT, "https://api.github.com/download/identity")))
        if request.full_url == "https://api.github.com/download/identity":
            return _FakeResponse(_zip_json(_pr_identity()))
        raise AssertionError(request.full_url)

    with patch.object(ci_run_timing.zipfile, "ZipFile", side_effect=zipfile.LargeZipFile("too big")):
        code = _main(
            _timing_argv(jobs, output, []),
            {"GITHUB_TOKEN": "t", "GITHUB_SHA": "f" * 40},
            opener,
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 2
    assert payload["success_execution_minutes"] == 10
    assert payload["reason"] == ci_run_timing.IDENTITY_UNAVAILABLE
    assert payload["identity"]["measurement_sha"] is None


def test_from_run_identity_corrupt_zip_keeps_cost(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job()]}), encoding="utf-8")
    output = tmp_path / "timing.json"

    def opener(request):
        if "artifacts?per_page=100" in request.full_url:
            return _FakeResponse(_identity_listing((ci_run_timing.IDENTITY_ARTIFACT, "https://api.github.com/download/identity")))
        if request.full_url == "https://api.github.com/download/identity":
            return _FakeResponse(b"PK\x03\x04not-a-zip")
        raise AssertionError(request.full_url)

    code = _main(
        _timing_argv(jobs, output, []),
        {"GITHUB_TOKEN": "t", "GITHUB_SHA": "f" * 40},
        opener,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 2
    assert payload["success_execution_minutes"] == 10
    assert payload["reason"] == ci_run_timing.IDENTITY_UNAVAILABLE
    assert payload["identity"]["measurement_sha"] is None


def test_from_run_identity_ignores_observer_github_sha(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job()]}), encoding="utf-8")
    output = tmp_path / "timing.json"

    def opener(request):
        if "artifacts?per_page=100" in request.full_url:
            return _FakeResponse(_identity_listing((ci_run_timing.IDENTITY_ARTIFACT, "https://api.github.com/download/identity")))
        if request.full_url == "https://api.github.com/download/identity":
            return _FakeResponse(_zip_json(_pr_identity()))
        raise AssertionError(request.full_url)

    code = _main(
        _timing_argv(jobs, output, []),
        {"GITHUB_TOKEN": "t", "GITHUB_SHA": "f" * 40},
        opener,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["complete"] is True
    assert payload["identity_complete"] is True
    assert payload["identity"]["measurement_sha"] == "b" * 40
    assert payload["identity"]["base_sha"] == "d" * 40
    assert payload["identity"]["measurement_sha"] != "f" * 40


def test_observer_cancelled_inner_runs_after_timing_failure() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci-run-timing-observer.yml"
    parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    steps = parsed["jobs"]["observe"]["steps"]
    names = [step["name"] for step in steps]
    record = next(step for step in steps if step["name"] == "Record cancelled Connected inner timing")
    timing = next(step for step in steps if step["name"] == "Record observed run timing")
    assert names.index("Record observed run timing") < names.index("Record cancelled Connected inner timing")
    assert "always()" in record["if"]
    assert "--from-run-identity" in record["run"]
    assert "--allow-partial" in record["run"]
    assert "--derive-cancelled-inner" in record["run"]
    assert record["env"]["GITHUB_TOKEN"]
    assert "--run-conclusion" in timing["run"]


def _observer_target_steps() -> tuple[dict, dict]:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci-run-timing-observer.yml"
    parsed = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    steps = parsed["jobs"]["observe"]["steps"]
    timing = next(step for step in steps if step["name"] == "Record observed run timing")
    cancelled = next(step for step in steps if step["name"] == "Record cancelled Connected inner timing")
    return timing, cancelled


def test_observer_workflow_passes_explicit_workflow_run_target() -> None:
    timing, cancelled = _observer_target_steps()
    text = Path(__file__).resolve().parents[2].joinpath(
        ".github", "workflows", "ci-run-timing-observer.yml",
    ).read_text(encoding="utf-8")
    assert "GITHUB_RUN_ID:" not in text
    assert "GITHUB_RUN_ATTEMPT:" not in text
    for step in (timing, cancelled):
        env = step.get("env") or {}
        assert "GITHUB_RUN_ID" not in env
        assert "GITHUB_RUN_ATTEMPT" not in env
        run = step["run"]
        assert "--github-repository" in run
        assert "--github-run-id" in run
        assert "--attempt" in run
        assert "${{ github.event.workflow_run.id }}" in run
        assert "${{ github.event.workflow_run.run_attempt }}" in run
        assert "${{ github.repository }}" in run


def test_from_github_uses_explicit_run_id_not_observer_github_run_id(tmp_path: Path) -> None:
    output = tmp_path / "timing.json"
    seen: list[str] = []
    current = _job(
        id=20, run_id=100, run_attempt=2,
        started_at="2026-09-18T03:00:00Z", completed_at="2026-09-18T03:10:00Z",
    )
    previous = _job(id=10, run_id=100, run_attempt=1)

    def opener(request):
        url = request.full_url
        seen.append(url)
        assert "/runs/999" not in url
        if "/runs/100/attempts/2/jobs" in url:
            return _FakeResponse({"jobs": [current]})
        if "/runs/100/attempts/1/jobs" in url:
            return _FakeResponse({"jobs": [previous]})
        if "/runs/100/artifacts?per_page=100" in url:
            return _FakeResponse(_identity_listing(
                (ci_run_timing.IDENTITY_ARTIFACT, "https://api.github.com/download/identity"),
            ))
        if url == "https://api.github.com/download/identity":
            return _FakeResponse(_zip_json(_pr_identity(run_id=100, run_attempt=2)))
        raise AssertionError(url)

    code = _main(
        [
            "--from-github",
            "--from-run-identity",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "100",
            "--attempt", "2",
            "--event", "pull_request",
            "--output-json", str(output),
        ],
        {
            "GITHUB_TOKEN": "t",
            "GITHUB_SHA": "f" * 40,
            "GITHUB_RUN_ID": "999",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "observer/should-not-matter",
        },
        opener,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0, payload
    assert payload["identity"]["run_id"] in {100, "100"}
    assert any("/runs/100/attempts/2/jobs" in url for url in seen)
    assert any("/runs/100/artifacts" in url for url in seen)
    assert all("/runs/999" not in url for url in seen)
    assert all("observer/should-not-matter" not in url for url in seen)


def test_derive_cancelled_inner_uses_explicit_run_id_not_observer_github_run_id(tmp_path: Path) -> None:
    inner = tmp_path / "connected-inner-timing.json"
    seen: list[str] = []
    job = _job(
        id=20, name="Connected execution", run_id=100, run_attempt=2,
        conclusion="cancelled",
        started_at="2026-09-18T03:00:00Z", completed_at="2026-09-18T03:08:00Z",
        steps=[{
            "name": "Run connected test",
            "conclusion": "cancelled",
            "started_at": "2026-09-18T03:01:00Z",
            "completed_at": "2026-09-18T03:08:00Z",
        }],
    )
    previous = _job(id=10, name="Connected execution", run_id=100, run_attempt=1)

    def opener(request):
        url = request.full_url
        seen.append(url)
        assert "/runs/999" not in url
        if "/runs/100/attempts/2/jobs" in url:
            return _FakeResponse({"jobs": [job]})
        if "/runs/100/attempts/1/jobs" in url:
            return _FakeResponse({"jobs": [previous]})
        if "/runs/100/artifacts?per_page=100" in url:
            return _FakeResponse(_identity_listing(
                (ci_run_timing.IDENTITY_ARTIFACT, "https://api.github.com/download/identity"),
            ))
        if url == "https://api.github.com/download/identity":
            return _FakeResponse(_zip_json(_pr_identity(
                run_id=100, run_attempt=2, workflow="Android Connected Test",
            )))
        raise AssertionError(url)

    code = _main(
        [
            "--stamp-connected-inner", str(inner),
            "--from-github",
            "--from-run-identity",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "100",
            "--attempt", "2",
            "--allow-partial",
            "--derive-cancelled-inner",
            "--job-name", "Connected execution",
            "--outer-step", "Run connected test",
        ],
        {
            "GITHUB_TOKEN": "t",
            "GITHUB_SHA": "f" * 40,
            "GITHUB_RUN_ID": "999",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REPOSITORY": "observer/should-not-matter",
        },
        opener,
    )
    payload = json.loads(inner.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["identity"]["run_id"] in {100, "100"}
    assert payload["state"] == "cancelled_during_connected"
    assert any("/runs/100/attempts/2/jobs" in url for url in seen)
    assert any("/runs/100/artifacts" in url for url in seen)
    assert all("/runs/999" not in url for url in seen)
    assert all("observer/should-not-matter" not in url for url in seen)


def test_cancelled_run_with_successful_jobs_reports_full_wasted_minutes() -> None:
    summary = ci_run_timing.summarize_jobs(
        [
            _job(id=1, name="Backend contracts", conclusion="success"),
            _job(
                id=2, name="Android fast", conclusion="success",
                started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:10:00Z",
            ),
            _job(
                id=3, name="Android APK release", conclusion="cancelled",
                started_at="2026-09-18T02:01:00Z", completed_at="2026-09-18T02:09:00Z",
            ),
        ],
        attempt=1,
        run_conclusion="cancelled",
    )
    assert summary["success_execution_minutes"] == 19
    assert summary["cancelled_execution_minutes"] == 8
    assert summary["total_execution_minutes"] == 27
    assert summary["wasted_execution_minutes"] == 27
    assert summary["run_conclusion"] == "cancelled"
    success_only = ci_run_timing.summarize_jobs([_job()], attempt=1, run_conclusion="success")
    assert success_only["wasted_execution_minutes"] == 0
    assert success_only["run_conclusion"] == "success"


def test_stamp_connected_inner_allow_partial_missing_elapsed_returns_zero(tmp_path: Path) -> None:
    inner = tmp_path / "connected-inner-timing.json"
    result = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "ci_run_timing.py"),
            "--stamp-connected-inner", str(inner),
            "--attempt", "1",
            "--allow-partial",
            "--inner-state", "started",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "1",
            "--workflow-name", "Android Connected Test",
            "--event", "pull_request",
            "--source-sha", "a" * 40,
            "--measurement-sha", "b" * 40,
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(inner.read_text(encoding="utf-8"))
    assert payload["complete"] is False
    assert payload["state"] == "started"


def test_pr_identity_without_base_sha_is_incomplete() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job()],
        attempt=1,
        report_identity=_pr_identity(base_sha=None),
    )
    assert summary["runner_execution_minutes"] == 10
    assert summary["identity_complete"] is False
    assert summary["complete"] is False
    assert any("base_sha" in item for item in summary["incomplete"])


def test_in_run_timing_workflow_carries_base_sha() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")
    _, _, timing = text.partition("Record observed runner timing")
    block, _, _rest = timing.partition("Upload CI run timing")
    assert "XPJ_WEIGHT_BASE_SHA:" in block
    assert "github.event.pull_request.base.sha" in block


def test_derive_missing_inner_state_from_job_evidence() -> None:
    assert ci_run_timing.derive_missing_inner_state([])[0] == "not_started"
    skipped = _job(name="Connected execution", conclusion="skipped", started_at=None, completed_at=None)
    assert ci_run_timing.derive_missing_inner_state([skipped])[0] == "not_started"
    cancelled = _job(
        name="Connected execution",
        conclusion="cancelled",
        steps=[{
            "name": "Run connected test",
            "conclusion": "cancelled",
            "started_at": "2026-09-18T02:02:00Z",
            "completed_at": "2026-09-18T02:08:00Z",
        }],
    )
    assert ci_run_timing.derive_missing_inner_state([cancelled])[0] == "cancelled_during_connected"
    finished = _job(
        name="Connected execution",
        conclusion="success",
        steps=[{
            "name": "Run connected test",
            "conclusion": "success",
            "started_at": "2026-09-18T02:02:00Z",
            "completed_at": "2026-09-18T02:08:00Z",
        }],
    )
    assert ci_run_timing.derive_missing_inner_state([finished])[0] == "finished_but_artifact_missing"


def test_derive_cancelled_inner_retains_existing_artifact(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job(
        name="Connected execution",
        conclusion="cancelled",
        steps=[{
            "name": "Run connected test",
            "conclusion": "cancelled",
            "started_at": "2026-09-18T02:02:00Z",
            "completed_at": "2026-09-18T02:08:00Z",
        }],
    )]}), encoding="utf-8")
    inner = tmp_path / "connected-inner-timing.json"
    retained = {"kind": "gradle_connected_test", "elapsed_s": 12.5, "state": "finalized", "complete": True}

    def opener(request):
        if "artifacts?per_page=100" in request.full_url:
            return _FakeResponse(_identity_listing(
                (ci_run_timing.IDENTITY_ARTIFACT, "https://api.github.com/download/identity"),
                (ci_run_timing.INNER_ARTIFACT, "https://api.github.com/download/inner"),
            ))
        if request.full_url == "https://api.github.com/download/identity":
            return _FakeResponse(_zip_json(_pr_identity(workflow="Android Connected Test")))
        if request.full_url == "https://api.github.com/download/inner":
            return _FakeResponse(_zip_json(retained, "connected-inner-timing.json"))
        raise AssertionError(request.full_url)

    code = _main(
        [
            "--stamp-connected-inner", str(inner),
            "--jobs-json", str(jobs),
            "--from-run-identity",
            "--derive-cancelled-inner",
            "--allow-partial",
            "--attempt", "1",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "100",
            "--job-name", "Connected execution",
            "--outer-step", "Run connected test",
        ],
        {"GITHUB_TOKEN": "t", "GITHUB_SHA": "f" * 40},
        opener,
    )
    payload = json.loads(inner.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["elapsed_s"] == 12.5
    assert payload["state"] == "finalized"


def test_derive_cancelled_inner_uses_target_identity_not_observer_sha(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [_job(
        name="Connected execution",
        conclusion="cancelled",
        steps=[{
            "name": "Run connected test",
            "conclusion": "cancelled",
            "started_at": "2026-09-18T02:02:00Z",
            "completed_at": "2026-09-18T02:08:00Z",
        }],
    )]}), encoding="utf-8")
    inner = tmp_path / "connected-inner-timing.json"

    def opener(request):
        if "artifacts?per_page=100" in request.full_url:
            return _FakeResponse(_identity_listing(
                (ci_run_timing.IDENTITY_ARTIFACT, "https://api.github.com/download/identity"),
            ))
        if request.full_url == "https://api.github.com/download/identity":
            return _FakeResponse(_zip_json(_pr_identity(
                workflow="Android Connected Test", measurement_sha="b" * 40,
            )))
        raise AssertionError(request.full_url)

    code = _main(
        [
            "--stamp-connected-inner", str(inner),
            "--jobs-json", str(jobs),
            "--from-run-identity",
            "--derive-cancelled-inner",
            "--allow-partial",
            "--attempt", "1",
            "--github-repository", "xxu29958-jpg/xpj",
            "--github-run-id", "100",
            "--job-name", "Connected execution",
            "--outer-step", "Run connected test",
        ],
        {"GITHUB_TOKEN": "t", "GITHUB_SHA": "f" * 40},
        opener,
    )
    payload = json.loads(inner.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["state"] == "cancelled_during_connected"
    assert payload["identity"]["measurement_sha"] == "b" * 40
    assert payload["identity"]["measurement_sha"] != "f" * 40
    assert payload["complete"] is False

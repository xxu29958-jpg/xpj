from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import ci_run_timing

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_attempt_listing_does_not_double_count_inherited_jobs() -> None:
    first = {
        "id": 1,
        "name": "Backend contracts",
        "conclusion": "success",
        "run_attempt": 1,
        "created_at": "2026-09-18T02:52:30Z",
        "started_at": "2026-09-18T02:52:34Z",
        "completed_at": "2026-09-18T02:59:38Z",
    }
    latest = {
        **first,
        "run_attempt": 2,
        "created_at": "2026-09-18T03:35:00Z",
    }
    summary = ci_run_timing.summarize_jobs([latest], attempt=2, previous_jobs=[first])
    assert summary["jobs"][0]["inherited"] is True
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False
    assert any("inherited" in item for item in summary["incomplete"])


def test_inverted_timestamps_are_incomplete_not_silently_zeroed() -> None:
    summary = ci_run_timing.summarize_jobs(
        [{
            "id": 2,
            "name": "inverted",
            "conclusion": "success",
            "started_at": "2026-09-18T04:00:00Z",
            "completed_at": "2026-09-18T03:00:00Z",
        }],
        attempt=1,
    )
    assert summary["jobs"][0]["inverted"] is True
    assert summary["jobs"][0]["execution_s"] is None
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False


def test_cancelled_consumed_time_is_listed_separately() -> None:
    summary = ci_run_timing.summarize_jobs(
        [{
            "id": 3,
            "name": "Android",
            "conclusion": "cancelled",
            "started_at": "2026-09-18T02:00:00Z",
            "completed_at": "2026-09-18T02:10:00Z",
        }],
        attempt=1,
    )
    assert summary["cancelled_consumed_minutes"] == 10
    assert summary["runner_execution_minutes"] == 10
    assert summary["complete"] is True


def test_cli_reads_fixture_jobs(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [{
        "id": 4,
        "name": "Connected",
        "conclusion": "success",
        "started_at": "2026-09-18T02:53:19Z",
        "completed_at": "2026-09-18T03:15:53Z",
        "steps": [{
            "name": "Run connected test",
            "conclusion": "success",
            "started_at": "2026-09-18T02:57:33Z",
            "completed_at": "2026-09-18T03:15:34Z",
        }],
    }]}), encoding="utf-8")
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


def _job(**fields: object) -> dict:
    row: dict[str, object] = {
        "id": 1,
        "name": "Backend contracts",
        "conclusion": "success",
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


def test_attempt_mismatch_contributes_zero_current_attempt_minutes() -> None:
    summary = ci_run_timing.summarize_jobs(
        [_job(run_attempt=1, started_at="2026-09-18T02:00:00Z", completed_at="2026-09-18T02:10:00Z")],
        attempt=2,
    )
    assert summary["runner_execution_minutes"] == 0
    assert summary["complete"] is False
    assert any("attempt mismatch" in item for item in summary["incomplete"])


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
    assert summary["runner_execution_minutes"] == 0
    assert any("inverted step" in item for item in summary["incomplete"])

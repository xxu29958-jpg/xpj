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

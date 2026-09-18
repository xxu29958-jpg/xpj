"""One-shot timing summary for already-finished GitHub Actions job pages."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def job_timing(job: dict, *, inherited: bool = False) -> dict[str, object]:
    started = parse_utc(job.get("started_at"))
    completed = parse_utc(job.get("completed_at"))
    created = parse_utc(job.get("created_at"))
    execution = _seconds(started, completed)
    inverted = execution is not None and execution < 0
    created_to_started = _seconds(created, started)
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "conclusion": job.get("conclusion"),
        "status": job.get("status"),
        "run_attempt": job.get("run_attempt"),
        "runner_labels": job.get("labels") or [],
        "inherited": inherited,
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "created_at": job.get("created_at"),
        "execution_s": None if inverted else execution,
        "execution_complete": execution is not None and not inverted,
        "inverted": inverted,
        "created_to_started_s": created_to_started,
        "created_to_started_meaning": "not pure runner queue; created_at may be the listing time",
        "steps": [
            {
                "name": step.get("name"),
                "conclusion": step.get("conclusion"),
                "started_at": step.get("started_at"),
                "completed_at": step.get("completed_at"),
                "elapsed_s": _seconds(parse_utc(step.get("started_at")), parse_utc(step.get("completed_at"))),
            }
            for step in job.get("steps") or []
        ],
    }


def summarize_jobs(
    jobs: list[dict],
    *,
    attempt: int | None = None,
    previous_jobs: list[dict] | None = None,
) -> dict[str, object]:
    previous = {
        row.get("id"): row
        for row in (previous_jobs or [])
        if isinstance(row, dict)
    }
    timed: list[dict[str, object]] = []
    incomplete: list[str] = []
    runner_seconds = 0.0
    cancelled_seconds = 0.0
    starts: list[datetime] = []
    ends: list[datetime] = []
    for job in jobs:
        prior = previous.get(job.get("id"))
        inherited = False
        if prior is not None:
            inherited = (
                prior.get("started_at") == job.get("started_at")
                and prior.get("completed_at") == job.get("completed_at")
                and prior.get("run_attempt") != job.get("run_attempt")
            )
        row = job_timing(job, inherited=inherited)
        if attempt is not None and job.get("run_attempt") not in {None, attempt} and not inherited:
            incomplete.append(f"{job.get('name')}: attempt mismatch")
        if row["inverted"]:
            incomplete.append(f"{job.get('name')}: inverted started/completed")
        elif row["inherited"]:
            incomplete.append(f"{job.get('name')}: inherited from an earlier attempt; not a new execution")
        elif row["execution_complete"]:
            seconds = float(row["execution_s"])
            if job.get("conclusion") == "cancelled":
                cancelled_seconds += seconds
            runner_seconds += seconds
            started = parse_utc(job.get("started_at"))
            completed = parse_utc(job.get("completed_at"))
            if started:
                starts.append(started)
            if completed:
                ends.append(completed)
        else:
            incomplete.append(f"{job.get('name')}: missing execution interval")
        timed.append(row)
    wall = _seconds(min(starts), max(ends)) if starts and ends else None
    return {
        "attempt": attempt,
        "jobs": timed,
        "runner_execution_minutes": round((runner_seconds) / 60, 3),
        "cancelled_consumed_minutes": round(cancelled_seconds / 60, 3),
        "wall_clock_s": wall,
        "coverage": "subset of supplied jobs only; not a full required-check wait",
        "incomplete": incomplete,
        "complete": not incomplete,
        "unit": "raw runner execution seconds / 60, not billed minutes",
    }


def render_timing(summary: dict[str, object]) -> str:
    lines = [
        f"CI RUN TIMING attempt={summary.get('attempt')} complete={summary.get('complete')}",
        f"runner_execution_minutes={summary['runner_execution_minutes']} ({summary['unit']})",
        f"cancelled_consumed_minutes={summary['cancelled_consumed_minutes']}",
        f"wall_clock_s={summary['wall_clock_s']}",
        f"coverage: {summary['coverage']}",
    ]
    for item in summary.get("incomplete") or []:
        lines.append(f"incomplete: {item}")
    for job in summary.get("jobs") or []:
        lines.append(
            f"job {job['name']} conclusion={job['conclusion']} inherited={job['inherited']} "
            f"execution_s={job['execution_s']} inverted={job['inverted']}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-json", type=Path, required=True)
    parser.add_argument("--previous-jobs-json", type=Path)
    parser.add_argument("--attempt", type=int)
    args = parser.parse_args()
    payload = json.loads(args.jobs_json.read_text(encoding="utf-8"))
    jobs = payload.get("jobs", payload) if isinstance(payload, dict) else payload
    previous = None
    if args.previous_jobs_json:
        prior = json.loads(args.previous_jobs_json.read_text(encoding="utf-8"))
        previous = prior.get("jobs", prior) if isinstance(prior, dict) else prior
    summary = summarize_jobs(jobs, attempt=args.attempt, previous_jobs=previous)
    print(render_timing(summary), end="")
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

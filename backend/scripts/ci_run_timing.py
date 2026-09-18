"""One-shot timing summary for already-finished GitHub Actions job pages."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

_INCOMPLETE_REASONS = {
    "mismatch": "attempt mismatch",
    "inherited": "inherited from an earlier attempt; not a new execution",
    "inverted": "inverted started/completed",
    "step_inverted": "inverted step started/completed",
    "missing": "missing execution interval",
}


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


def _step_row(step: dict) -> dict[str, object]:
    elapsed = _seconds(parse_utc(step.get("started_at")), parse_utc(step.get("completed_at")))
    inverted = elapsed is not None and elapsed < 0
    return {
        "name": step.get("name"),
        "conclusion": step.get("conclusion"),
        "started_at": step.get("started_at"),
        "completed_at": step.get("completed_at"),
        "elapsed_s": None if inverted else elapsed,
        "inverted": inverted,
    }


def job_timing(job: dict, *, inherited: bool = False) -> dict[str, object]:
    started = parse_utc(job.get("started_at"))
    completed = parse_utc(job.get("completed_at"))
    created = parse_utc(job.get("created_at"))
    execution = _seconds(started, completed)
    inverted = execution is not None and execution < 0
    steps = [_step_row(step) for step in job.get("steps") or []]
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "conclusion": job.get("conclusion"),
        "status": job.get("status"),
        "run_id": job.get("run_id"),
        "head_sha": job.get("head_sha"),
        "workflow_name": job.get("workflow_name"),
        "run_attempt": job.get("run_attempt"),
        "runner_labels": job.get("labels") or [],
        "inherited": inherited,
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "created_at": job.get("created_at"),
        "execution_s": None if inverted else execution,
        "execution_complete": execution is not None and not inverted,
        "inverted": inverted,
        "created_to_started_s": _seconds(created, started),
        "created_to_started_meaning": "not pure runner queue; created_at may be the listing time",
        "steps": steps,
        "step_inverted": any(bool(step["inverted"]) for step in steps),
    }


def _is_inherited(job: dict, prior: dict | None) -> bool:
    if prior is None:
        return False
    return (
        prior.get("started_at") == job.get("started_at")
        and prior.get("completed_at") == job.get("completed_at")
        and prior.get("run_attempt") != job.get("run_attempt")
    )


def _identity_values(jobs: list[dict], key: str) -> set[object]:
    return {job.get(key) for job in jobs if isinstance(job, dict) and job.get(key) not in {None, ""}}


def _shared_identity(jobs: list[dict]) -> dict[str, object]:
    run_ids = _identity_values(jobs, "run_id")
    shas = _identity_values(jobs, "head_sha")
    workflows = _identity_values(jobs, "workflow_name")
    mixed = len(run_ids) > 1 or len(shas) > 1 or len(workflows) > 1
    return {
        "run_id": next(iter(run_ids)) if len(run_ids) == 1 else None,
        "head_sha": next(iter(shas)) if len(shas) == 1 else None,
        "workflow_name": next(iter(workflows)) if len(workflows) == 1 else None,
        "mixed": mixed,
    }


def _status_for(job: dict, row: dict[str, object], attempt: int | None) -> str:
    if attempt is not None and job.get("run_attempt") not in {None, attempt} and not row["inherited"]:
        return "mismatch"
    if row["inherited"]:
        return "inherited"
    if job.get("conclusion") == "skipped":
        return "skipped"
    if row["inverted"]:
        return "inverted"
    if row.get("step_inverted"):
        return "step_inverted"
    if row["execution_complete"]:
        return "billed"
    return "missing"


def _bill_seconds(row: dict[str, object], conclusion: object, buckets: dict[str, float]) -> float:
    seconds = float(row["execution_s"] or 0)
    if conclusion in buckets:
        buckets[str(conclusion)] += seconds
    return seconds


def _record_interval(job: dict, starts: list[datetime], ends: list[datetime]) -> None:
    started, completed = parse_utc(job.get("started_at")), parse_utc(job.get("completed_at"))
    if started:
        starts.append(started)
    if completed:
        ends.append(completed)


def _apply_status(
    job: dict,
    row: dict[str, object],
    status: str,
    identity: dict[str, object],
    incomplete: list[str],
    skipped: list[str],
    buckets: dict[str, float],
    starts: list[datetime],
    ends: list[datetime],
) -> None:
    if status == "skipped":
        skipped.append(str(job.get("name")))
        return
    if status in _INCOMPLETE_REASONS:
        incomplete.append(f"{job.get('name')}: {_INCOMPLETE_REASONS[status]}")
        return
    if status != "billed" or identity["mixed"]:
        return
    _bill_seconds(row, job.get("conclusion"), buckets)
    _record_interval(job, starts, ends)


def summarize_jobs(
    jobs: list[dict],
    *,
    attempt: int | None = None,
    previous_jobs: list[dict] | None = None,
) -> dict[str, object]:
    identity = _shared_identity(jobs)
    previous = {row.get("id"): row for row in (previous_jobs or []) if isinstance(row, dict)}
    timed: list[dict[str, object]] = []
    incomplete: list[str] = []
    skipped: list[str] = []
    buckets = {"success": 0.0, "failure": 0.0, "cancelled": 0.0}
    starts: list[datetime] = []
    ends: list[datetime] = []
    if identity["mixed"]:
        incomplete.append("mixed run_id, workflow_name, or head_sha")
    for job in jobs:
        row = job_timing(job, inherited=_is_inherited(job, previous.get(job.get("id"))))
        status = _status_for(job, row, attempt)
        row["timing_status"] = status
        _apply_status(job, row, status, identity, incomplete, skipped, buckets, starts, ends)
        timed.append(row)
    billed = buckets["success"] + buckets["failure"] + buckets["cancelled"]
    return {
        "attempt": attempt,
        "run_id": identity["run_id"],
        "workflow_name": identity["workflow_name"],
        "head_sha": identity["head_sha"],
        "jobs": timed,
        "runner_execution_minutes": round(billed / 60, 3),
        "success_execution_minutes": round(buckets["success"] / 60, 3),
        "failure_execution_minutes": round(buckets["failure"] / 60, 3),
        "cancelled_consumed_minutes": round(buckets["cancelled"] / 60, 3),
        "skipped_jobs": skipped,
        "observed_subset_wall_clock_s": _seconds(min(starts), max(ends)) if starts and ends else None,
        "coverage": "observed subset of supplied jobs only; not the final required-check wait",
        "incomplete": incomplete,
        "complete": not incomplete,
        "unit": "raw runner execution seconds / 60, not billed minutes",
    }


def _job_line(job: dict) -> list[str]:
    lines = [
        f"job {job['name']} conclusion={job['conclusion']} inherited={job['inherited']} "
        f"queue_s={job['created_to_started_s']} execution_s={job['execution_s']} inverted={job['inverted']}"
    ]
    for step in job.get("steps") or []:
        lines.append(
            f"  step {step['name']} conclusion={step['conclusion']} "
            f"elapsed_s={step['elapsed_s']} inverted={step['inverted']}"
        )
    return lines


def render_timing(summary: dict[str, object]) -> str:
    skipped = summary.get("skipped_jobs") or []
    lines = [
        f"CI RUN TIMING attempt={summary.get('attempt')} complete={summary.get('complete')}",
        f"run_id={summary.get('run_id')} workflow_name={summary.get('workflow_name')} head_sha={summary.get('head_sha')}",
        f"runner_execution_minutes={summary['runner_execution_minutes']} ({summary['unit']})",
        f"success_execution_minutes={summary['success_execution_minutes']}",
        f"failure_execution_minutes={summary['failure_execution_minutes']}",
        f"cancelled_consumed_minutes={summary['cancelled_consumed_minutes']}",
        f"skipped_jobs={len(skipped)}",
        f"observed_subset_wall_clock_s={summary['observed_subset_wall_clock_s']}",
        f"coverage: {summary['coverage']}",
    ]
    for item in summary.get("incomplete") or []:
        lines.append(f"incomplete: {item}")
    for name in skipped:
        lines.append(f"skipped: {name}")
    for job in summary.get("jobs") or []:
        lines.extend(_job_line(job))
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

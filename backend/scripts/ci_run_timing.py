"""One-shot timing summary for already-finished GitHub Actions job pages."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_INCOMPLETE_REASONS = {
    "mismatch": "attempt mismatch",
    "inverted": "inverted started/completed",
    "step_inverted": "inverted step started/completed",
    "step_missing": "executed step missing timestamps",
    "step_unknown": "unknown step conclusion",
    "missing": "missing execution interval",
    "identity": "missing required job identity",
    "unsupported": "unsupported or missing conclusion",
}

_NAMED_BUCKETS = {
    "success": "success",
    "failure": "failure",
    "cancelled": "cancelled",
    "neutral": "neutral",
}
_EXECUTED_STEP = frozenset({"success", "failure", "cancelled"})
_KNOWN_STEP = _EXECUTED_STEP | {"skipped"}
_JOB_IDENTITY = ("run_id", "workflow_name", "head_sha", "run_attempt", "status", "conclusion")
_JOB_INTERVAL = ("started_at", "completed_at")
_GITHUB_API = "https://api.github.com"


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


def _queue_fields(created: datetime | None, started: datetime | None) -> tuple[float | None, str]:
    elapsed = _seconds(created, started)
    if elapsed is None:
        return None, "missing"
    if elapsed < 0:
        return None, "created_after_start"
    return elapsed, "created_to_started"


def _step_row(step: dict) -> dict[str, object]:
    elapsed = _seconds(parse_utc(step.get("started_at")), parse_utc(step.get("completed_at")))
    inverted = elapsed is not None and elapsed < 0
    conclusion = step.get("conclusion")
    return {
        "name": step.get("name"),
        "conclusion": conclusion,
        "started_at": step.get("started_at"),
        "completed_at": step.get("completed_at"),
        "elapsed_s": None if inverted else elapsed,
        "inverted": inverted,
        "unknown_conclusion": conclusion not in _KNOWN_STEP and conclusion not in {None, ""},
        "executed_missing_time": conclusion in _EXECUTED_STEP and elapsed is None,
    }


def _step_fingerprint(steps: object) -> tuple[tuple[object, object, object, object], ...]:
    rows = []
    for step in steps or []:
        if isinstance(step, dict):
            rows.append((step.get("name"), step.get("conclusion"), step.get("started_at"), step.get("completed_at")))
    return tuple(rows)


def _job_fingerprint(job: dict) -> tuple[object, ...]:
    return (
        job.get("workflow_name"),
        job.get("head_sha"),
        job.get("name"),
        job.get("started_at"),
        job.get("completed_at"),
        job.get("conclusion"),
        _step_fingerprint(job.get("steps")),
    )


def job_timing(job: dict, *, inherited: bool = False) -> dict[str, object]:
    started = parse_utc(job.get("started_at"))
    completed = parse_utc(job.get("completed_at"))
    created = parse_utc(job.get("created_at"))
    execution = _seconds(started, completed)
    inverted = execution is not None and execution < 0
    steps = [_step_row(step) for step in job.get("steps") or [] if isinstance(step, dict)]
    queue_s, queue_status = _queue_fields(created, started)
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
        "queue_s": queue_s,
        "queue_status": queue_status,
        "created_to_started_s": _seconds(created, started),
        "created_to_started_meaning": "not pure runner queue; created_at may be the listing time",
        "steps": steps,
        "step_inverted": any(bool(step["inverted"]) for step in steps),
        "step_missing_time": any(bool(step["executed_missing_time"]) for step in steps),
        "step_unknown": any(bool(step["unknown_conclusion"]) for step in steps),
    }


def _attempt_number(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _previous_same_scope(job: dict, prior: dict) -> bool:
    prior_attempt = _attempt_number(prior.get("run_attempt"))
    current_attempt = _attempt_number(job.get("run_attempt"))
    return (
        prior.get("run_id") == job.get("run_id")
        and prior.get("workflow_name") == job.get("workflow_name")
        and prior.get("head_sha") == job.get("head_sha")
        and prior_attempt is not None
        and current_attempt is not None
        and prior_attempt < current_attempt
    )


def _claim_inherited(job: dict, unused: list[dict]) -> bool:
    fingerprint = _job_fingerprint(job)
    for index, prior in enumerate(unused):
        if _job_fingerprint(prior) != fingerprint or not _previous_same_scope(job, prior):
            continue
        unused.pop(index)
        return True
    return False


def _identity_values(jobs: list[dict], key: str) -> set[object]:
    return {job.get(key) for job in jobs if isinstance(job, dict) and job.get(key) not in {None, ""}}


def _shared_identity(jobs: list[dict]) -> dict[str, object]:
    run_ids = _identity_values(jobs, "run_id")
    shas = _identity_values(jobs, "head_sha")
    workflows = _identity_values(jobs, "workflow_name")
    mixed = len(run_ids) > 1 or len(shas) > 1 or len(workflows) > 1
    missing = not run_ids or not shas or not workflows
    return {
        "run_id": next(iter(run_ids)) if len(run_ids) == 1 else None,
        "head_sha": next(iter(shas)) if len(shas) == 1 else None,
        "workflow_name": next(iter(workflows)) if len(workflows) == 1 else None,
        "mixed": mixed,
        "missing": missing,
    }


def _is_skipped(job: dict) -> bool:
    return job.get("conclusion") == "skipped" or job.get("status") == "skipped"


def _missing_job_fields(job: dict) -> list[str]:
    required = _JOB_IDENTITY if _is_skipped(job) else _JOB_IDENTITY + _JOB_INTERVAL
    return [field for field in required if job.get(field) in {None, ""}]


def _step_status(row: dict[str, object]) -> str | None:
    if row.get("step_inverted"):
        return "step_inverted"
    if row.get("step_missing_time"):
        return "step_missing"
    if row.get("step_unknown"):
        return "step_unknown"
    return None


def _status_for(job: dict, row: dict[str, object], attempt: int | None) -> str:
    if _missing_job_fields(job):
        return "identity"
    if attempt is not None and job.get("run_attempt") not in {None, attempt} and not row["inherited"]:
        return "mismatch"
    if row["inherited"]:
        return "inherited"
    if _is_skipped(job):
        return "skipped"
    if row["inverted"]:
        return "inverted"
    step_status = _step_status(row)
    if step_status:
        return step_status
    if not row["execution_complete"]:
        return "missing"
    if _bucket_for(job.get("conclusion")) == "other":
        return "unsupported"
    return "billed"


def _bucket_for(conclusion: object) -> str | None:
    if conclusion == "skipped":
        return None
    return _NAMED_BUCKETS.get(str(conclusion) if conclusion not in {None, ""} else "", "other")


def _empty_buckets() -> dict[str, float]:
    return {"success": 0.0, "failure": 0.0, "cancelled": 0.0, "neutral": 0.0, "other": 0.0}


def _record_interval(job: dict, starts: list[datetime], ends: list[datetime]) -> None:
    started, completed = parse_utc(job.get("started_at")), parse_utc(job.get("completed_at"))
    if started:
        starts.append(started)
    if completed:
        ends.append(completed)


def _bill_row(row: dict[str, object], conclusion: object, buckets: dict[str, float]) -> None:
    seconds = float(row["execution_s"] or 0)
    bucket = _bucket_for(conclusion)
    if bucket:
        buckets[bucket] += seconds


def _same_run_scope(prior_identity: dict[str, object], identity: dict[str, object]) -> bool:
    return (
        prior_identity["run_id"] == identity["run_id"]
        and prior_identity["workflow_name"] == identity["workflow_name"]
        and prior_identity["head_sha"] == identity["head_sha"]
    )


def _attempts_older_than(rows: list[dict], attempt: int | None) -> bool:
    if attempt is None:
        return True
    return all((_attempt_number(row.get("run_attempt")) or attempt) < attempt for row in rows)


def _previous_ready(
    previous_jobs: list[dict] | None,
    attempt: int | None,
    identity: dict[str, object],
) -> tuple[list[dict], list[str]]:
    if attempt is not None and attempt > 1 and not previous_jobs:
        return [], ["attempt > 1 without previous-attempt evidence"]
    if not previous_jobs:
        return [], []
    prior_identity = _shared_identity(previous_jobs)
    if prior_identity["mixed"] or prior_identity["missing"]:
        return [], ["previous attempt identity is mixed or missing"]
    if not _same_run_scope(prior_identity, identity):
        return [], ["previous attempt is not the same run/workflow/head"]
    usable = [row for row in previous_jobs if isinstance(row, dict)]
    if not _attempts_older_than(usable, attempt):
        return [], ["previous attempt must be less than the current attempt"]
    return usable, []


def _can_bill(identity: dict[str, object], previous_notes: list[str]) -> bool:
    return not identity["mixed"] and not any("previous-attempt evidence" in note for note in previous_notes)


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
    previous_notes: list[str],
) -> None:
    name = str(job.get("name"))
    if status == "skipped":
        skipped.append(name)
        return
    if status == "inherited":
        return
    if status in _INCOMPLETE_REASONS:
        extra = ""
        if status == "identity":
            extra = f" ({', '.join(_missing_job_fields(job))})"
        elif status == "unsupported":
            extra = f" ({job.get('conclusion')!r})"
        incomplete.append(f"{name}: {_INCOMPLETE_REASONS[status]}{extra}")
        if status == "unsupported" and row["execution_complete"] and _can_bill(identity, previous_notes):
            _bill_row(row, job.get("conclusion"), buckets)
            _record_interval(job, starts, ends)
        return
    if status != "billed" or not _can_bill(identity, previous_notes):
        return
    _bill_row(row, job.get("conclusion"), buckets)
    _record_interval(job, starts, ends)


def summarize_jobs(
    jobs: list[dict],
    *,
    attempt: int | None = None,
    previous_jobs: list[dict] | None = None,
) -> dict[str, object]:
    identity = _shared_identity(jobs)
    unused, previous_notes = _previous_ready(previous_jobs, attempt, identity)
    timed: list[dict[str, object]] = []
    incomplete: list[str] = []
    skipped: list[str] = []
    buckets = _empty_buckets()
    starts: list[datetime] = []
    ends: list[datetime] = []
    if identity["mixed"]:
        incomplete.append("mixed run_id, workflow_name, or head_sha")
    if identity["missing"]:
        incomplete.append("missing shared run_id, workflow_name, or head_sha")
    incomplete.extend(previous_notes)
    for job in jobs:
        if not isinstance(job, dict):
            continue
        row = job_timing(job, inherited=_claim_inherited(job, unused))
        status = _status_for(job, row, attempt)
        row["timing_status"] = status
        _apply_status(
            job, row, status, identity, incomplete, skipped, buckets, starts, ends, previous_notes,
        )
        timed.append(row)
    total = sum(buckets.values())
    return {
        "attempt": attempt,
        "run_id": identity["run_id"],
        "workflow_name": identity["workflow_name"],
        "head_sha": identity["head_sha"],
        "jobs": timed,
        "runner_execution_minutes": round(total / 60, 3),
        "total_execution_minutes": round(total / 60, 3),
        "success_execution_minutes": round(buckets["success"] / 60, 3),
        "failure_execution_minutes": round(buckets["failure"] / 60, 3),
        "cancelled_consumed_minutes": round(buckets["cancelled"] / 60, 3),
        "cancelled_execution_minutes": round(buckets["cancelled"] / 60, 3),
        "neutral_execution_minutes": round(buckets["neutral"] / 60, 3),
        "other_execution_minutes": round(buckets["other"] / 60, 3),
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
        f"queue_s={job['queue_s']} queue_status={job['queue_status']} "
        f"execution_s={job['execution_s']} inverted={job['inverted']}"
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
        f"total_execution_minutes={summary['total_execution_minutes']}",
        f"success_execution_minutes={summary['success_execution_minutes']}",
        f"failure_execution_minutes={summary['failure_execution_minutes']}",
        f"cancelled_execution_minutes={summary['cancelled_execution_minutes']}",
        f"neutral_execution_minutes={summary['neutral_execution_minutes']}",
        f"other_execution_minutes={summary['other_execution_minutes']}",
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


def _read_job_list(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs", payload) if isinstance(payload, dict) else payload
    if not isinstance(jobs, list):
        raise ValueError("jobs JSON must be a list or an object with jobs")
    return [row for row in jobs if isinstance(row, dict)]


def fetch_github_jobs(
    repository: str,
    run_id: int,
    attempt: int,
    token: str,
    *,
    urlopen=urllib.request.urlopen,
) -> list[dict]:
    jobs: list[dict] = []
    for page in range(1, 21):
        url = (
            f"{_GITHUB_API}/repos/{repository}/actions/runs/{run_id}"
            f"/attempts/{attempt}/jobs?per_page=100&page={page}"
        )
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ticketbox-ci-run-timing",
            },
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        chunk = payload.get("jobs", []) if isinstance(payload, dict) else []
        jobs.extend(row for row in chunk if isinstance(row, dict))
        if len(chunk) < 100:
            return jobs
    raise ValueError("github jobs pagination exceeded 20 pages")


def _write_outputs(summary: dict[str, object], rendered: str, args: argparse.Namespace) -> None:
    if args.output_json:
        args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.summary:
        fence = chr(96) * 3
        with args.summary.open("a", encoding="utf-8") as output:
            output.write("### CI run timing\n\n" + fence + "text\n" + rendered + fence + "\n")


def _load_github_pair(args: argparse.Namespace) -> tuple[list[dict], list[dict] | None, int]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repository = args.github_repository or os.environ.get("GITHUB_REPOSITORY")
    run_id = args.github_run_id or os.environ.get("GITHUB_RUN_ID")
    attempt = args.attempt or int(os.environ.get("GITHUB_RUN_ATTEMPT") or "0")
    if not token or not repository or not run_id or attempt < 1:
        raise ValueError("GitHub timing needs token, repository, run id, and attempt")
    current = fetch_github_jobs(repository, int(run_id), attempt, token)
    previous = None
    if attempt > 1:
        previous = fetch_github_jobs(repository, int(run_id), attempt - 1, token)
    return current, previous, attempt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-json", type=Path)
    parser.add_argument("--previous-jobs-json", type=Path)
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--from-github", action="store_true")
    parser.add_argument("--github-repository")
    parser.add_argument("--github-run-id", type=int)
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = parser.parse_args()
    try:
        if args.from_github:
            jobs, previous, attempt = _load_github_pair(args)
        else:
            if args.jobs_json is None:
                raise ValueError("--jobs-json is required unless --from-github is set")
            jobs = _read_job_list(args.jobs_json)
            previous = _read_job_list(args.previous_jobs_json) if args.previous_jobs_json else None
            attempt = args.attempt
        summary = summarize_jobs(jobs, attempt=attempt, previous_jobs=previous)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"CI RUN TIMING INCOMPLETE: {exc}", file=sys.stderr)
        return 2
    rendered = render_timing(summary)
    print(rendered, end="")
    _write_outputs(summary, rendered, args)
    if args.observe:
        return 0
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

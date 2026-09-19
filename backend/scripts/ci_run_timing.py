"""On-demand timing collector for already-finished GitHub Actions runs."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

_QUALIFICATION_LOG = re.compile(
    r"Qualification checkout SHA: ([0-9a-f]{40}); source SHA: ([0-9a-f]{40})"
)
_GITHUB_LOG_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T[0-9:.]+Z\s+")
_AUDIT_LANE = re.compile(r"(?:^|\s)AUDIT_LANE_TIMING\s+(\{.*\})\s*$")
_AUDIT_RUN = re.compile(r"(?:^|\s)AUDIT_RUN_TIMING\s+(\{.*\})\s*$")
_LOAD_CATCH = (
    OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
    urllib.error.URLError, zipfile.BadZipFile, zipfile.LargeZipFile,
)

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
_STEP_DETAIL = frozenset({"step_inverted", "step_missing", "step_unknown"})
_NO_BILL = frozenset({"inherited", "skipped", "mismatch", "identity", "inverted", "missing"})
_NAMED_BUCKETS = {
    "success": "success",
    "failure": "failure",
    "timed_out": "timed_out",
    "cancelled": "cancelled",
    "neutral": "neutral",
}
_EXECUTED_STEP = frozenset({"success", "failure", "timed_out", "cancelled"})
_SCOPE_LOG_JOBS = {
    "CI": ("CI scope",),
    "CodeQL": ("CodeQL scope",),
    "Android Connected Test": ("Connected scope",),
}
_AUDIT_LOG_JOBS = {"CI": ("Backend contracts",)}
_KNOWN_STEP = _EXECUTED_STEP | {"skipped"}
_JOB_IDENTITY = ("run_id", "workflow_name", "head_sha", "run_attempt", "status", "conclusion")
_JOB_INTERVAL = ("started_at", "completed_at")
_PREFERRED_RUNNERS = ("ubuntu-latest", "windows-latest", "macos-latest")
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


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def _minutes(seconds: float) -> float:
    return round(seconds / 60, 3)


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
    return {
        "success": 0.0,
        "failure": 0.0,
        "timed_out": 0.0,
        "cancelled": 0.0,
        "neutral": 0.0,
        "other": 0.0,
    }


def _conclusion_view(buckets: dict[str, float]) -> dict[str, float]:
    return {
        "success": _minutes(buckets["success"]),
        "failure": _minutes(buckets["failure"]),
        "timed_out": _minutes(buckets["timed_out"]),
        "cancelled": _minutes(buckets["cancelled"]),
        "other": _minutes(buckets["neutral"] + buckets["other"]),
    }


def _platform_for(job: dict) -> str:
    labels = [str(item) for item in (job.get("labels") or []) if item not in {None, ""}]
    for name in _PREFERRED_RUNNERS:
        if name in labels:
            return name
    return labels[0] if labels else "unknown"


def _record_interval(job: dict, starts: list[datetime], ends: list[datetime]) -> None:
    started, completed = parse_utc(job.get("started_at")), parse_utc(job.get("completed_at"))
    if started:
        starts.append(started)
    if completed:
        ends.append(completed)


def _bill_row(
    job: dict,
    row: dict[str, object],
    buckets: dict[str, float],
    platforms: dict[str, float],
) -> None:
    seconds = float(row["execution_s"] or 0)
    bucket = _bucket_for(job.get("conclusion"))
    if not bucket:
        return
    buckets[bucket] += seconds
    platform = _platform_for(job)
    platforms[platform] = platforms.get(platform, 0.0) + seconds


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
    return not identity["mixed"] and not identity["missing"] and not previous_notes


def _interval_billable(
    status: str,
    row: dict[str, object],
    identity: dict[str, object],
    previous_notes: list[str],
) -> bool:
    if status in _NO_BILL or not row.get("execution_complete"):
        return False
    return _can_bill(identity, previous_notes)


def _status_note(job: dict, status: str) -> str:
    extra = ""
    if status == "identity":
        extra = f" ({', '.join(_missing_job_fields(job))})"
    elif status == "unsupported":
        extra = f" ({job.get('conclusion')!r})"
    return f"{job.get('name')}: {_INCOMPLETE_REASONS[status]}{extra}"


def _apply_qualification_overlay(
    bundles: list[dict[str, object]],
    pairs: list[tuple[str, str]],
) -> None:
    if len(pairs) != 1:
        return
    checkout, _source = pairs[0]
    for bundle in bundles:
        if not bundle.get("checkout_sha"):
            bundle["checkout_sha"] = checkout


def _apply_status(
    job: dict,
    row: dict[str, object],
    status: str,
    identity: dict[str, object],
    incomplete: list[str],
    skipped: list[str],
    buckets: dict[str, float],
    platforms: dict[str, float],
    starts: list[datetime],
    ends: list[datetime],
    previous_notes: list[str],
) -> None:
    if status == "skipped":
        skipped.append(str(job.get("name")))
        return
    if status == "inherited":
        return
    if status in _INCOMPLETE_REASONS:
        incomplete.append(_status_note(job, status))
    if _interval_billable(status, row, identity, previous_notes):
        _bill_row(job, row, buckets, platforms)
        _record_interval(job, starts, ends)


def summarize_jobs(
    jobs: list[dict],
    *,
    attempt: int | None = None,
    previous_jobs: list[dict] | None = None,
) -> dict[str, object]:
    visible = [job for job in jobs if isinstance(job, dict)]
    identity = _shared_identity(visible)
    unused, previous_notes = _previous_ready(previous_jobs, attempt, identity)
    timed: list[dict[str, object]] = []
    incomplete: list[str] = []
    skipped: list[str] = []
    buckets = _empty_buckets()
    platforms: dict[str, float] = {}
    starts: list[datetime] = []
    ends: list[datetime] = []
    if identity["mixed"]:
        incomplete.append("mixed run_id, workflow_name, or head_sha")
    if identity["missing"]:
        incomplete.append("missing shared run_id, workflow_name, or head_sha")
    incomplete.extend(previous_notes)
    for job in visible:
        row = job_timing(job, inherited=_claim_inherited(job, unused))
        status = _status_for(job, row, attempt)
        row["timing_status"] = status
        _apply_status(
            job, row, status, identity, incomplete, skipped, buckets, platforms, starts, ends, previous_notes,
        )
        timed.append(row)
    total = sum(buckets.values())
    step_incomplete = any(row.get("timing_status") in _STEP_DETAIL for row in timed)
    return {
        "attempt": attempt,
        "run_id": identity["run_id"],
        "workflow_name": identity["workflow_name"],
        "head_sha": identity["head_sha"],
        "jobs": timed,
        "runner_execution_minutes": _minutes(total),
        "total_execution_minutes": _minutes(total),
        "success_execution_minutes": _minutes(buckets["success"]),
        "failure_execution_minutes": _minutes(buckets["failure"]),
        "timed_out_execution_minutes": _minutes(buckets["timed_out"]),
        "cancelled_consumed_minutes": _minutes(buckets["cancelled"]),
        "cancelled_execution_minutes": _minutes(buckets["cancelled"]),
        "neutral_execution_minutes": _minutes(buckets["neutral"]),
        "other_execution_minutes": _minutes(buckets["other"]),
        "by_platform": {name: _minutes(seconds) for name, seconds in sorted(platforms.items())},
        "by_conclusion": _conclusion_view(buckets),
        "skipped_jobs": skipped,
        "observed_subset_wall_clock_s": _seconds(min(starts), max(ends)) if starts and ends else None,
        "coverage": "observed subset of supplied jobs only; not the final required-check wait",
        "incomplete": incomplete,
        "step_timing_complete": not step_incomplete,
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
    if "runner_execution" in summary:
        return _render_report(summary)
    skipped = summary.get("skipped_jobs") or []
    lines = [
        f"CI RUN TIMING attempt={summary.get('attempt')} complete={summary.get('complete')}",
        f"run_id={summary.get('run_id')} workflow_name={summary.get('workflow_name')} head_sha={summary.get('head_sha')}",
        f"step_timing_complete={summary.get('step_timing_complete')}",
        f"runner_execution_minutes={summary['runner_execution_minutes']} ({summary['unit']})",
        f"total_execution_minutes={summary['total_execution_minutes']}",
        f"success_execution_minutes={summary['success_execution_minutes']}",
        f"failure_execution_minutes={summary['failure_execution_minutes']}",
        f"cancelled_execution_minutes={summary['cancelled_execution_minutes']}",
        f"by_platform={summary.get('by_platform')}",
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


def _render_report(report: dict[str, object]) -> str:
    execution = report.get("runner_execution") or {}
    wait = report.get("required_gate_wait") or {}
    subject = report.get("subject") or {}
    lines = [
        f"CI RUN TIMING complete={report.get('complete')} identity_complete={report.get('identity_complete')}",
        f"repository={subject.get('repository')} event={subject.get('event')} "
        f"source_sha={subject.get('source_sha')} base_sha={subject.get('base_sha')}",
        f"known_minutes={execution.get('known_minutes')} by_platform={execution.get('by_platform')}",
        f"by_conclusion={execution.get('by_conclusion')}",
        f"required_gate_wait complete={wait.get('complete')} "
        f"elapsed_from_created_s={wait.get('elapsed_from_created_s')} "
        f"elapsed_from_started_s={wait.get('elapsed_from_started_s')} "
        f"missing_checks={wait.get('missing_checks')}",
    ]
    for item in report.get("incomplete_reasons") or []:
        lines.append(f"incomplete: {item}")
    for row in report.get("cancellations") or []:
        lines.append(
            f"cancelled run_id={row.get('run_id')} consumed_minutes={row.get('consumed_minutes')} "
            f"cause={row.get('cause')} cause_confidence={row.get('cause_confidence')}"
        )
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
    urlopen=None,
) -> list[dict]:
    opener = urlopen or urllib.request.urlopen
    jobs: list[dict] = []
    for page in range(1, 21):
        url = (
            f"{_GITHUB_API}/repos/{repository}/actions/runs/{run_id}"
            f"/attempts/{attempt}/jobs?per_page=100&page={page}"
        )
        payload = _github_json(url, token, urlopen=opener)
        chunk = payload.get("jobs", []) if isinstance(payload, dict) else []
        jobs.extend(row for row in chunk if isinstance(row, dict))
        if len(chunk) < 100:
            return jobs
    raise ValueError("github jobs pagination exceeded 20 pages")


def fetch_github_run(
    repository: str,
    run_id: int,
    token: str,
    *,
    urlopen=None,
) -> dict:
    opener = urlopen or urllib.request.urlopen
    return _github_json(f"{_GITHUB_API}/repos/{repository}/actions/runs/{run_id}", token, urlopen=opener)


def _github_json(url: str, token: str, *, urlopen=None) -> dict:
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ticketbox-ci-run-timing",
        },
    )
    with opener(request) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub JSON object required")
    return payload


def parse_qualification_log(text: str) -> tuple[str, str] | None:
    match = _QUALIFICATION_LOG.search(text)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _log_lines(text: str) -> list[str]:
    cleaned = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.split("\n")


def _marker_payload(line: str, pattern: re.Pattern[str]) -> dict[str, object] | None:
    stripped = _GITHUB_LOG_PREFIX.sub("", line.strip())
    match = pattern.search(stripped) or pattern.search(line)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError("audit timing JSON is invalid") from exc
    return payload if isinstance(payload, dict) else None


def parse_audit_lane_timing(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in _log_lines(text):
        payload = _marker_payload(line, _AUDIT_LANE)
        if payload is not None:
            rows.append(payload)
    return rows


def parse_audit_run_markers(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in _log_lines(text):
        payload = _marker_payload(line, _AUDIT_RUN)
        if payload is not None:
            rows.append(payload)
    return rows


def parse_audit_run_timing(text: str) -> dict[str, object] | None:
    rows = parse_audit_run_markers(text)
    return rows[0] if len(rows) == 1 else None


def _resolve_audit_run(markers: list[dict[str, object]]) -> tuple[dict[str, object] | None, list[str]]:
    if len(markers) > 1:
        return None, ["duplicate AUDIT_RUN_TIMING markers"]
    if len(markers) == 1:
        return markers[0], []
    return None, []


def _run_is_finished(metadata: dict) -> bool:
    return metadata.get("status") == "completed"


def _named_step(jobs: list[dict], name: str) -> dict | None:
    for job in jobs:
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == name:
                return step
    return None


def _job_with_step(jobs: list[dict], name: str) -> dict | None:
    for job in jobs:
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == name:
                return job
    return None


def _matching_prior_job(job: dict | None, previous_jobs: list[dict]) -> dict | None:
    if job is None:
        return None
    fingerprint = _job_fingerprint(job)
    for prior in previous_jobs:
        if isinstance(prior, dict) and _job_fingerprint(prior) == fingerprint and _previous_same_scope(job, prior):
            return prior
    return None


def _phase_row(name: str, phase: str, kind: str, step: dict | None) -> dict[str, object]:
    elapsed = None
    if step is not None:
        elapsed = _seconds(parse_utc(step.get("started_at")), parse_utc(step.get("completed_at")))
        if elapsed is not None and elapsed < 0:
            elapsed = None
    return {
        "name": name,
        "phase": phase,
        "measurement_kind": kind if step is not None or kind == "unknown" else "unknown",
        "elapsed_s": elapsed,
        "source_step": None if step is None else step.get("name"),
    }


def _derived_span(jobs: list[dict], start_name: str, end_name: str) -> dict[str, object]:
    start = _named_step(jobs, start_name)
    end = _named_step(jobs, end_name)
    if start is None or end is None:
        return {
            "measurement_kind": "unknown",
            "elapsed_s": None,
            "source_step": None,
        }
    elapsed = _seconds(parse_utc(start.get("started_at")), parse_utc(end.get("completed_at")))
    if elapsed is not None and elapsed < 0:
        elapsed = None
    return {
        "measurement_kind": "derived",
        "elapsed_s": elapsed,
        "source_step": f"{start_name} -> {end_name}",
    }


def _origin_job(job: dict | None, attempts: list[dict[str, object]]) -> dict | None:
    if job is None:
        return None
    origin = None
    for item in attempts:
        prior_jobs = [row for row in (item.get("jobs") or []) if isinstance(row, dict)]
        match = _matching_prior_job(job, prior_jobs)
        if match is not None:
            origin = match
            break
    return origin


def _phase_attempt_fields(
    jobs: list[dict],
    attempts: list[dict[str, object]],
    target_attempt: int,
    step_name: str,
) -> dict[str, object]:
    origin = _origin_job(_job_with_step(jobs, step_name), attempts)
    if origin is None:
        return {"attempt": target_attempt, "evidence_attempt": target_attempt, "inherited": False}
    evidence = _attempt_number(origin.get("run_attempt")) or target_attempt
    return {
        "attempt": target_attempt,
        "evidence_attempt": evidence,
        "inherited": evidence != target_attempt,
    }


def _annotate_phase(
    row: dict[str, object],
    jobs: list[dict],
    attempts: list[dict[str, object]],
    target_attempt: int,
    step_name: str,
) -> dict[str, object]:
    row.update(_phase_attempt_fields(jobs, attempts, target_attempt, step_name))
    return row


def android_phases_from_attempts(attempts: list[dict[str, object]]) -> list[dict[str, object]]:
    latest = attempts[-1] if attempts else {"attempt": 1, "jobs": []}
    jobs = [job for job in (latest.get("jobs") or []) if isinstance(job, dict)]
    target = _attempt_number(latest.get("attempt")) or 1
    configuration = _annotate_phase(
        {"name": "configuration", "phase": "configuration", **_derived_span(jobs, "Set up Java", "Accept Android SDK licenses")},
        jobs, attempts, target, "Set up Java",
    )
    return [
        configuration,
        _annotate_phase(
            _phase_row("compile", "compile", "direct", _named_step(jobs, "Precompile connected APKs")),
            jobs, attempts, target, "Precompile connected APKs",
        ),
        _annotate_phase(
            {
                "name": "cache_state",
                "phase": "cache",
                "measurement_kind": "unknown",
                "elapsed_s": None,
                "source_step": "Set up Gradle",
            },
            jobs, attempts, target, "Set up Gradle",
        ),
        _annotate_phase(
            _phase_row(
                "emulator_prepare_install_test_exit",
                "emulator_prepare + install + test + exit",
                "combined",
                _named_step(jobs, "Run connected test"),
            ),
            jobs, attempts, target, "Run connected test",
        ),
        _annotate_phase(
            _phase_row(
                "checkout_qualification",
                "checkout qualification",
                "direct",
                _named_step(jobs, "Verify qualification SHA"),
            ),
            jobs, attempts, target, "Verify qualification SHA",
        ),
        _annotate_phase(
            _phase_row(
                "result_qualification",
                "result qualification",
                "direct",
                _named_step(jobs, "Enforce Connected result"),
            ),
            jobs, attempts, target, "Enforce Connected result",
        ),
    ]


def android_phases_from_jobs(jobs: list[dict]) -> list[dict[str, object]]:
    return android_phases_from_attempts([{"attempt": 1, "jobs": jobs}])


def cancellation_record(run_id: object, consumed_minutes: float) -> dict[str, object]:
    return {
        "run_id": run_id,
        "consumed_minutes": consumed_minutes,
        "cause": "unknown",
        "cause_confidence": "unknown",
    }


def _merge_minutes(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    merged = dict(left)
    for name, value in right.items():
        merged[name] = round(merged.get(name, 0.0) + value, 3)
    return merged


def _record_required_job(job: dict, required_checks: list[str], completed: dict[str, datetime]) -> None:
    name = job.get("name")
    if name not in required_checks or job.get("conclusion") in {None, "", "skipped"}:
        return
    ended = parse_utc(job.get("completed_at"))
    if ended is None:
        return
    previous = completed.get(str(name))
    if previous is None or ended > previous:
        completed[str(name)] = ended


def _collect_gate_times(
    bundles: list[dict[str, object]],
    required_checks: list[str],
) -> tuple[list[datetime], list[datetime], dict[str, datetime]]:
    created: list[datetime] = []
    started: list[datetime] = []
    completed: dict[str, datetime] = {}
    for bundle in bundles:
        metadata = bundle.get("metadata") or {}
        created_at = parse_utc(metadata.get("created_at"))
        started_at = parse_utc(metadata.get("run_started_at"))
        if created_at:
            created.append(created_at)
        if started_at:
            started.append(started_at)
        for job in _iter_bundle_jobs(bundle):
            _record_required_job(job, required_checks, completed)
    return created, started, completed


def _gate_span_ok(created: datetime | None, started: datetime | None, last: datetime | None) -> bool:
    if created is None or started is None or last is None:
        return False
    return created <= started <= last


def _inferred_attempts(bundle: dict[str, object]) -> list[dict[str, object]]:
    metadata = bundle.get("metadata") or {}
    attempt = _attempt_number(bundle.get("attempt") or metadata.get("run_attempt")) or 1
    jobs = [job for job in (bundle.get("jobs") or []) if isinstance(job, dict)]
    previous = [job for job in (bundle.get("previous_jobs") or []) if isinstance(job, dict)]
    if previous and attempt > 1:
        return [{"attempt": attempt - 1, "jobs": previous}, {"attempt": attempt, "jobs": jobs}]
    return [{"attempt": attempt, "jobs": jobs}]


def _bundle_attempts(bundle: dict[str, object]) -> list[dict[str, object]]:
    raw = bundle.get("attempts")
    if not isinstance(raw, list) or not raw:
        return _inferred_attempts(bundle)
    rows = [item for item in raw if isinstance(item, dict) and item.get("jobs") is not None]
    return sorted(rows, key=lambda item: _attempt_number(item.get("attempt")) or 0)


def _iter_bundle_jobs(bundle: dict[str, object]):
    for item in _bundle_attempts(bundle):
        for job in item.get("jobs") or []:
            if isinstance(job, dict):
                yield job


def required_gate_wait(bundles: list[dict[str, object]], required_checks: list[str]) -> dict[str, object]:
    created, started, completed = _collect_gate_times(bundles, required_checks)
    missing = [name for name in required_checks if name not in completed]
    last = max(completed.values()) if completed else None
    first_created = min(created) if created else None
    first_started = min(started) if started else None
    workflow_errors = [note for bundle in bundles for note in _workflow_time_notes(bundle)]
    return {
        "complete": (
            bool(required_checks)
            and not missing
            and not workflow_errors
            and _gate_span_ok(first_created, first_started, last)
        ),
        "trigger_created_at": _utc_text(first_created),
        "first_workflow_started_at": _utc_text(first_started),
        "last_required_check_completed_at": _utc_text(last),
        "elapsed_from_created_s": _seconds(first_created, last),
        "elapsed_from_started_s": _seconds(first_started, last),
        "missing_checks": missing,
        "required_checks": list(required_checks),
        "required_check_source": "explicit_cli",
        "workflow_time_errors": workflow_errors,
    }


def _unique_meta(bundles: list[dict[str, object]], key: str) -> set[object]:
    values = {(bundle.get("metadata") or {}).get(key) for bundle in bundles}
    values.discard(None)
    values.discard("")
    return values


def _base_shas(bundles: list[dict[str, object]]) -> set[str]:
    bases: set[str] = set()
    for bundle in bundles:
        for pull in bundle.get("metadata", {}).get("pull_requests") or []:
            if isinstance(pull, dict) and (pull.get("base") or {}).get("sha"):
                bases.add(str((pull.get("base") or {}).get("sha")))
    return bases


def _one_value(values: set[object], name: str) -> tuple[object | None, str | None]:
    if not values:
        return None, f"missing {name}"
    if len(values) > 1:
        return None, f"mixed {name}"
    return next(iter(values)), None


def _identity_source_notes(source: object | None, log_sources: set[object]) -> list[str]:
    if len(log_sources) > 1:
        return ["mixed qualification source"]
    if log_sources and source is not None and source not in log_sources:
        return [f"qualification source mismatch: {next(iter(log_sources))} != {source}"]
    return []


def _identity_checkout_notes(log_checkouts: set[str], bundle_checkouts: set[str]) -> list[str]:
    if log_checkouts and bundle_checkouts and log_checkouts != bundle_checkouts:
        return ["mixed checkout SHA"]
    return []


def _identity_base_note(event: object | None, base_note: str | None) -> str | None:
    if base_note == "mixed base_sha" or (event == "pull_request" and base_note):
        return base_note
    return None


def _bundle_checkout(bundle: dict[str, object]) -> str | None:
    if bundle.get("checkout_sha"):
        return str(bundle.get("checkout_sha"))
    metadata = bundle.get("metadata") or {}
    if metadata.get("checkout_sha"):
        return str(metadata.get("checkout_sha"))
    return None


def _bundle_source(bundle: dict[str, object]) -> str | None:
    if bundle.get("source_sha"):
        return str(bundle.get("source_sha"))
    metadata = bundle.get("metadata") or {}
    return metadata.get("head_sha") or metadata.get("source_sha")


def subject_from_bundles(
    repository: str | None,
    bundles: list[dict[str, object]],
    qualification: list[tuple[str, str]],
) -> tuple[dict[str, object], bool, list[str]]:
    notes: list[str] = []
    event, event_note = _one_value(_unique_meta(bundles, "event"), "event")
    source, source_note = _one_value(_unique_meta(bundles, "head_sha"), "source_sha")
    base, base_note = _one_value(_base_shas(bundles), "base_sha")
    log_sources = {item[1] for item in qualification}
    log_checkouts = {item[0] for item in qualification}
    bundle_checkouts = {sha for sha in (_bundle_checkout(bundle) for bundle in bundles) if sha}
    checkout, checkout_note = _one_value(log_checkouts or bundle_checkouts, "checkout SHA")
    for note in (event_note, source_note, checkout_note, _identity_base_note(event, base_note)):
        if note:
            notes.append(note)
    notes.extend(_identity_source_notes(source, log_sources))
    notes.extend(_identity_checkout_notes(log_checkouts, bundle_checkouts))
    return (
        {
            "repository": repository,
            "event": event,
            "source_sha": source,
            "checkout_shas": [checkout] if checkout else [],
            "base_sha": base,
        },
        not notes,
        notes,
    )


def _final_job_completed_at(bundle: dict[str, object]) -> str | None:
    ended = [parse_utc(job.get("completed_at")) for job in _iter_bundle_jobs(bundle)]
    present = [item for item in ended if item is not None]
    return _utc_text(max(present)) if present else None


def _workflow_time_notes(bundle: dict[str, object]) -> list[str]:
    metadata = bundle.get("metadata") or {}
    name = str(metadata.get("name") or metadata.get("id") or "workflow")
    created = parse_utc(metadata.get("created_at"))
    started = parse_utc(metadata.get("run_started_at"))
    final = parse_utc(_final_job_completed_at(bundle))
    notes: list[str] = []
    if created is None:
        notes.append(f"missing created_at for {name}")
    if started is None:
        notes.append(f"missing run_started_at for {name}")
    if _run_is_finished(metadata) and final is None:
        notes.append(f"missing final_job_completed_at for {name}")
    if created is not None and started is not None and final is not None and not (created <= started <= final):
        notes.append(f"inverted workflow timestamps for {name}")
    return notes


def _actual_job_bounds(jobs: list[dict[str, object]]) -> tuple[str | None, str | None]:
    starts = [item for item in (parse_utc(job.get("started_at")) for job in jobs) if item is not None]
    ends = [item for item in (parse_utc(job.get("completed_at")) for job in jobs) if item is not None]
    return (
        _utc_text(min(starts) if starts else None),
        _utc_text(max(ends) if ends else None),
    )


def _attempt_row(summary: dict[str, object]) -> dict[str, object]:
    jobs = [job for job in summary.get("jobs") or [] if isinstance(job, dict)]
    actual = [job for job in jobs if not job.get("inherited")]
    inherited_only = bool(jobs) and not actual
    started, completed = (None, None) if inherited_only else _actual_job_bounds(actual)
    return {
        "attempt": summary["attempt"],
        "actual_execution_minutes": summary["runner_execution_minutes"],
        "inherited_job_count": sum(1 for job in jobs if job.get("inherited")),
        "complete": summary["complete"],
        "by_platform": summary["by_platform"],
        "by_conclusion": summary["by_conclusion"],
        "incomplete": summary["incomplete"],
        "first_actual_job_started_at": started,
        "last_actual_job_completed_at": completed,
        "execution_state": "inherited_only" if inherited_only else "completed",
        "measurement_kind": "derived_from_jobs",
    }


def _merge_conclusions(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    merged = dict(left)
    for key, value in right.items():
        if key in merged:
            merged[key] = round(merged[key] + float(value), 3)
    return merged


def _workflow_row(
    bundle: dict[str, object],
    metadata: dict,
    run_id: object,
    attempt_rows: list[dict[str, object]],
    latest: dict[str, object],
    total_minutes: float,
) -> dict[str, object]:
    name = metadata.get("name") or latest.get("workflow_name")
    platforms: dict[str, float] = {}
    conclusions = {"success": 0.0, "failure": 0.0, "timed_out": 0.0, "cancelled": 0.0, "other": 0.0}
    incomplete: list[str] = []
    for row in attempt_rows:
        platforms = _merge_minutes(platforms, dict(row.get("by_platform") or {}))
        conclusions = _merge_conclusions(conclusions, dict(row.get("by_conclusion") or {}))
        incomplete.extend(str(item) for item in row.get("incomplete") or [])
    return {
        "run_id": latest.get("run_id") or run_id,
        "name": name,
        "event": metadata.get("event"),
        "source_sha": _bundle_source(bundle),
        "checkout_sha": _bundle_checkout(bundle),
        "base_sha": next(iter(_base_shas([bundle])), None),
        "created_at": metadata.get("created_at"),
        "run_started_at": metadata.get("run_started_at"),
        "final_job_completed_at": _final_job_completed_at(bundle),
        "final_job_completed_at_kind": "derived_from_job_completed_at",
        "status": metadata.get("status"),
        "conclusion": metadata.get("conclusion"),
        "attempt": latest.get("attempt") or metadata.get("run_attempt"),
        "attempts": attempt_rows,
        "complete": bool(attempt_rows) and all(row.get("complete") for row in attempt_rows),
        "runner_execution_minutes": total_minutes,
        "by_platform": platforms,
        "by_conclusion": conclusions,
        "incomplete": incomplete,
    }


def _add_minutes(totals: dict[str, object], summary: dict[str, object]) -> None:
    totals["platforms"] = _merge_minutes(totals["platforms"], dict(summary.get("by_platform") or {}))
    by_conclusion = dict(summary.get("by_conclusion") or {})
    for key in totals["conclusions"]:
        totals["conclusions"][key] = round(totals["conclusions"][key] + float(by_conclusion.get(key) or 0), 3)
    totals["known"] = round(totals["known"] + float(summary["runner_execution_minutes"]), 3)


def _summarize_attempts(bundle: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object], float]:
    rows: list[dict[str, object]] = []
    previous_jobs: list[dict] | None = None
    latest: dict[str, object] = summarize_jobs([])
    total = 0.0
    for item in _bundle_attempts(bundle):
        attempt = _attempt_number(item.get("attempt")) or 1
        jobs = [job for job in (item.get("jobs") or []) if isinstance(job, dict)]
        latest = summarize_jobs(jobs, attempt=attempt, previous_jobs=previous_jobs)
        rows.append(_attempt_row(latest))
        total = round(total + float(latest["runner_execution_minutes"]), 3)
        previous_jobs = jobs
    return rows, latest, total


def _note_special_workflow(
    bundle: dict[str, object],
    metadata: dict,
    total_minutes: float,
    run_id: object,
    totals: dict[str, object],
) -> None:
    if metadata.get("conclusion") == "cancelled":
        totals["cancellations"].append(cancellation_record(run_id, total_minutes))
    if metadata.get("name") == "Android Connected Test":
        totals["android_attempts"] = _bundle_attempts(bundle)


def _attempt_gap_notes(bundle: dict[str, object]) -> list[str]:
    metadata = bundle.get("metadata") or {}
    expected = _attempt_number(metadata.get("run_attempt") or bundle.get("attempt"))
    if expected is None:
        return ["missing attempt"]
    have = {_attempt_number(item.get("attempt")) for item in _bundle_attempts(bundle)}
    missing = [index for index in range(1, expected + 1) if index not in have]
    if not missing:
        return []
    name = metadata.get("name") or metadata.get("id")
    return [f"missing attempt {index} jobs for {name}" for index in missing]


def _add_bundle(
    bundle: dict[str, object],
    totals: dict[str, object],
) -> None:
    metadata = bundle.get("metadata") or {}
    run_id = metadata.get("id") or bundle.get("run_id")
    if metadata and not _run_is_finished(metadata):
        totals["incomplete"].append(f"unfinished run {run_id}")
        totals["runner_complete"] = False
    attempt_rows, latest, total_minutes = _summarize_attempts(bundle)
    for row in attempt_rows:
        if not row.get("complete"):
            totals["runner_complete"] = False
            totals["incomplete"].extend(str(item) for item in row.get("incomplete") or [])
        _add_minutes(totals, {
            "by_platform": row.get("by_platform") or {},
            "by_conclusion": row.get("by_conclusion") or {},
            "runner_execution_minutes": row.get("actual_execution_minutes") or 0,
        })
    gap_notes = _attempt_gap_notes(bundle)
    if gap_notes:
        totals["runner_complete"] = False
        totals["incomplete"].extend(gap_notes)
    _note_special_workflow(bundle, metadata, total_minutes, run_id, totals)
    workflow = _workflow_row(bundle, metadata, run_id, attempt_rows, latest, total_minutes)
    if gap_notes:
        workflow["complete"] = False
        workflow["incomplete"] = list(workflow.get("incomplete") or []) + gap_notes
    totals["workflows"].append(workflow)


def _gate_times_ordered(wait: dict[str, object]) -> bool:
    created = parse_utc(wait.get("trigger_created_at"))
    started = parse_utc(wait.get("first_workflow_started_at"))
    last = parse_utc(wait.get("last_required_check_completed_at"))
    if created is None or started is None or last is None:
        return True
    return created <= started <= last


def _wait_notes(wait: dict[str, object], required_checks: list[str]) -> list[str]:
    if not required_checks:
        return ["required-check set not supplied"]
    if wait["complete"]:
        return []
    notes: list[str] = []
    if wait.get("missing_checks"):
        notes.append(f"missing required checks: {', '.join(wait['missing_checks'])}")
    if not wait.get("trigger_created_at"):
        notes.append("missing created_at")
    if not wait.get("first_workflow_started_at"):
        notes.append("missing run_started_at")
    if not _gate_times_ordered(wait):
        notes.append("inverted required-gate wait timestamps")
    notes.extend(str(item) for item in wait.get("workflow_time_errors") or [])
    return notes or ["required-check wait is incomplete"]


def _backend_contracts_executed(bundles: list[dict[str, object]]) -> bool:
    for bundle in bundles:
        for job in _iter_bundle_jobs(bundle):
            if job.get("name") == "Backend contracts" and job.get("conclusion") in _EXECUTED_STEP:
                return True
    return False


def _lane_names(audit_lanes: list[dict[str, object]]) -> list[str]:
    return [str(lane.get("lane")) for lane in audit_lanes if lane.get("lane") not in {None, ""}]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_negative_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value >= 0


def _lane_identity_notes(lane: dict[str, object]) -> list[str]:
    name = lane.get("lane")
    notes: list[str] = []
    if name in {None, ""}:
        notes.append("audit lane name missing")
        name = "lane"
    if lane.get("filename") in {None, ""}:
        notes.append(f"audit lane filename missing: {name}")
    if not _is_int(lane.get("returncode")):
        notes.append(f"audit lane returncode missing: {name}")
    return notes


def _lane_timing_notes(lane: dict[str, object]) -> list[str]:
    name = str(lane.get("lane") or "lane")
    notes: list[str] = []
    started = parse_utc(lane.get("started_utc"))
    ended = parse_utc(lane.get("ended_utc"))
    if started is None:
        notes.append(f"audit lane started_utc missing: {name}")
    if ended is None:
        notes.append(f"audit lane ended_utc missing: {name}")
    if started is not None and ended is not None and started > ended:
        notes.append(f"audit lane inverted timestamps: {name}")
    if not _is_non_negative_number(lane.get("elapsed_s")):
        notes.append(f"audit lane elapsed_s missing: {name}")
    return notes


def _lane_clock_notes(lane: dict[str, object]) -> list[str]:
    name = str(lane.get("lane") or "lane")
    notes: list[str] = []
    if lane.get("elapsed_clock") != "monotonic":
        notes.append(f"audit lane elapsed_clock invalid: {name}")
    if lane.get("measurement_kind") != "direct":
        notes.append(f"audit lane measurement_kind invalid: {name}")
    if lane.get("complete") is not True:
        notes.append(f"audit lane timing incomplete: {name}")
    return notes


def _lane_set_notes(expected: list[str], names: list[str]) -> list[str]:
    notes: list[str] = []
    if len(expected) != len(set(expected)):
        notes.append("audit run expected lanes are not unique")
    if len(names) != len(set(names)):
        notes.append("duplicate audit lanes")
    missing = [name for name in expected if name not in names]
    extra = [name for name in names if name not in expected]
    if missing:
        notes.append(f"missing audit lanes: {', '.join(missing)}")
    if extra:
        notes.append(f"unexpected audit lanes: {', '.join(extra)}")
    return notes


def _audit_count_notes(audit_run: dict[str, object], expected: list[str], names: list[str]) -> list[str]:
    notes: list[str] = []
    if audit_run.get("expected_lane_count") != len(expected):
        notes.append("audit run expected_lane_count mismatch")
    if audit_run.get("completed_lane_count") != len(names):
        notes.append("audit run completed_lane_count mismatch")
    if audit_run.get("complete") is not True:
        notes.append("audit run timing incomplete")
    if not _is_int(audit_run.get("overall_returncode")):
        notes.append("audit run overall_returncode missing")
    return notes


def _audit_set_notes(
    audit_lanes: list[dict[str, object]],
    audit_run: dict[str, object] | None,
) -> list[str]:
    if not audit_run:
        return ["audit lane timing unavailable"]
    expected = [str(name) for name in (audit_run.get("expected_lanes") or [])]
    names = _lane_names(audit_lanes)
    notes: list[str] = []
    if not expected:
        notes.append("audit run expected_lanes missing")
    notes.extend(_lane_set_notes(expected, names))
    notes.extend(_audit_count_notes(audit_run, expected, names))
    for lane in audit_lanes:
        notes.extend(_lane_identity_notes(lane))
        notes.extend(_lane_timing_notes(lane))
        notes.extend(_lane_clock_notes(lane))
    return notes


def _latest_audit_step(bundles: list[dict[str, object]]) -> dict | None:
    for bundle in bundles:
        job = _find_named_job(bundle, "Backend contracts")
        if job is None:
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == "Audit (release lanes)":
                return step
    return None


def _audit_step_contradiction(
    bundles: list[dict[str, object]],
    audit_run: dict[str, object] | None,
) -> str | None:
    if not audit_run:
        return None
    overall = audit_run.get("overall_returncode")
    step = _latest_audit_step(bundles)
    if step is None:
        return "audit step missing"
    conclusion = step.get("conclusion")
    if conclusion == "success" and _is_int(overall) and overall != 0:
        return "audit overall returncode contradicts Audit (release lanes) success"
    if conclusion in {"failure", "timed_out", "cancelled"} and overall == 0:
        return f"audit overall returncode contradicts Audit (release lanes) {conclusion}"
    return None


def _workflow_evidence_notes(bundle: dict[str, object]) -> list[str]:
    metadata = bundle.get("metadata") or {}
    name = str(metadata.get("name") or metadata.get("id") or "workflow")
    notes: list[str] = []
    if not metadata.get("event"):
        notes.append(f"missing event for {name}")
    if not _bundle_source(bundle):
        notes.append(f"missing source SHA for {name}")
    if not _bundle_checkout(bundle):
        notes.append(f"missing checkout SHA for {name}")
    if metadata.get("id") in {None, ""} and bundle.get("run_id") in {None, ""}:
        notes.append(f"missing run_id for {name}")
    if _attempt_number(metadata.get("run_attempt") or bundle.get("attempt")) is None:
        notes.append(f"missing attempt for {name}")
    return notes


def _strict_complete_notes(
    bundles: list[dict[str, object]],
    *,
    required_checks: list[str],
    wait: dict[str, object],
    identity_notes: list[str],
    audit_lanes: list[dict[str, object]],
    audit_run: dict[str, object] | None,
    evidence_errors: list[str],
    runner_complete: bool,
) -> list[str]:
    notes = list(evidence_errors)
    notes.extend(identity_notes)
    notes.extend(_wait_notes(wait, required_checks))
    for bundle in bundles:
        notes.extend(_workflow_evidence_notes(bundle))
        notes.extend(_attempt_gap_notes(bundle))
        metadata = bundle.get("metadata") or {}
        if metadata and not _run_is_finished(metadata):
            notes.append(f"unfinished run {metadata.get('id')}")
    if _backend_contracts_executed(bundles):
        notes.extend(_audit_set_notes(audit_lanes, audit_run))
        contradiction = _audit_step_contradiction(bundles, audit_run)
        if contradiction:
            notes.append(contradiction)
    if not runner_complete:
        notes.append("runner cost incomplete")
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for item in notes:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def build_report(
    bundles: list[dict[str, object]],
    *,
    repository: str | None = None,
    required_checks: list[str] | None = None,
    audit_lanes: list[dict[str, object]] | None = None,
    qualification: list[tuple[str, str]] | None = None,
    audit_run: dict[str, object] | None = None,
    evidence_errors: list[str] | None = None,
) -> dict[str, object]:
    totals: dict[str, object] = {
        "incomplete": [],
        "workflows": [],
        "platforms": {},
        "conclusions": {
            "success": 0.0, "failure": 0.0, "timed_out": 0.0, "cancelled": 0.0, "other": 0.0,
        },
        "cancellations": [],
        "android_attempts": [],
        "known": 0.0,
        "runner_complete": True,
    }
    pairs = list(qualification or [])
    _apply_qualification_overlay(bundles, pairs)
    for bundle in bundles:
        _add_bundle(bundle, totals)
    subject, identity_complete, identity_notes = subject_from_bundles(
        repository, bundles, pairs,
    )
    checks = list(required_checks or [])
    wait = required_gate_wait(bundles, checks)
    incomplete = _strict_complete_notes(
        bundles,
        required_checks=checks,
        wait=wait,
        identity_notes=identity_notes + list(totals["incomplete"]),
        audit_lanes=list(audit_lanes or []),
        audit_run=audit_run,
        evidence_errors=list(evidence_errors or []),
        runner_complete=bool(totals["runner_complete"]),
    )
    return {
        "subject": subject,
        "identity_complete": identity_complete,
        "workflows": totals["workflows"],
        "runner_execution": {
            "complete": totals["runner_complete"],
            "known_minutes": totals["known"],
            "known_partial": not bool(totals["runner_complete"]),
            "by_platform": totals["platforms"],
            "by_conclusion": totals["conclusions"],
        },
        "required_gate_wait": wait,
        "audit_lanes": list(audit_lanes or []),
        "audit_run": audit_run,
        "android_phases": android_phases_from_attempts(list(totals["android_attempts"])),
        "cancellations": totals["cancellations"],
        "incomplete_reasons": incomplete,
        "complete": not incomplete,
        "unit": "raw runner execution seconds / 60, not billed minutes",
    }


def _write_outputs(summary: dict[str, object], rendered: str, args: argparse.Namespace) -> None:
    if args.output_json:
        args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.summary:
        fence = chr(96) * 3
        with args.summary.open("a", encoding="utf-8") as output:
            output.write("### CI run timing\n\n" + fence + "text\n" + rendered + fence + "\n")


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _decode_log_blob(blob: bytes) -> str:
    if blob.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            parts = [archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist()]
        return "\n".join(parts)
    return blob.decode("utf-8", errors="replace")


def fetch_job_logs(
    repository: str,
    job_id: int,
    token: str,
    *,
    urlopen=None,
) -> str:
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(
        f"{_GITHUB_API}/repos/{repository}/actions/jobs/{job_id}/logs",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ticketbox-ci-run-timing",
        },
    )
    with opener(request) as response:
        return _decode_log_blob(response.read())


def _find_named_job(bundle: dict[str, object], name: str) -> dict | None:
    for item in reversed(_bundle_attempts(bundle)):
        for job in item.get("jobs") or []:
            if (
                isinstance(job, dict)
                and job.get("name") == name
                and job.get("id") not in {None, ""}
                and job.get("conclusion") != "skipped"
            ):
                return job
    return None


def attach_remote_evidence(
    bundles: list[dict[str, object]],
    repository: str,
    token: str,
    *,
    urlopen=None,
) -> tuple[list[tuple[str, str]], list[dict[str, object]], dict[str, object] | None, list[str]]:
    qualification: list[tuple[str, str]] = []
    audit_lanes: list[dict[str, object]] = []
    markers: list[dict[str, object]] = []
    errors: list[str] = []
    for bundle in bundles:
        metadata = bundle.get("metadata") or {}
        workflow = str(metadata.get("name") or "")
        for job_name in _SCOPE_LOG_JOBS.get(workflow, ()):
            job = _find_named_job(bundle, job_name)
            if job is None:
                errors.append(f"missing checkout SHA for {workflow}")
                continue
            try:
                text = fetch_job_logs(repository, int(job["id"]), token, urlopen=urlopen)
            except _LOAD_CATCH:
                errors.append(f"missing checkout SHA for {workflow}")
                continue
            parsed = parse_qualification_log(text)
            if parsed is None:
                errors.append(f"missing checkout SHA for {workflow}")
                continue
            bundle["checkout_sha"] = parsed[0]
            qualification.append(parsed)
        for job_name in _AUDIT_LOG_JOBS.get(workflow, ()):
            job = _find_named_job(bundle, job_name)
            if job is None:
                continue
            try:
                text = fetch_job_logs(repository, int(job["id"]), token, urlopen=urlopen)
                audit_lanes.extend(parse_audit_lane_timing(text))
                markers.extend(parse_audit_run_markers(text))
            except _LOAD_CATCH:
                errors.append("audit lane timing unavailable")
    audit_run, run_errors = _resolve_audit_run(markers)
    errors.extend(run_errors)
    return qualification, audit_lanes, audit_run, errors


def _load_remote_bundles(args: argparse.Namespace) -> list[dict[str, object]]:
    token = _token()
    repository = args.repository or os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository or not args.run_ids:
        raise ValueError("GitHub timing needs token, --repository, and at least one --run-id")
    bundles = []
    for run_id in args.run_ids:
        metadata = fetch_github_run(repository, run_id, token)
        latest = _attempt_number(metadata.get("run_attempt")) or 1
        attempts = []
        for attempt in range(1, latest + 1):
            try:
                attempts.append({
                    "attempt": attempt,
                    "jobs": fetch_github_jobs(repository, run_id, attempt, token),
                })
            except _LOAD_CATCH:
                continue
        bundles.append({
            "metadata": metadata,
            "attempts": attempts,
            "attempt": latest,
        })
    return bundles


def _local_metadata(args: argparse.Namespace, payload: dict) -> dict[str, object]:
    metadata = dict(payload.get("metadata") or {})
    metadata.setdefault("id", args.run_ids[0] if args.run_ids else None)
    metadata.setdefault("name", args.workflow_name)
    metadata.setdefault("event", args.event)
    metadata.setdefault("head_sha", args.source_sha)
    metadata.setdefault("status", "completed")
    metadata.setdefault("conclusion", args.run_conclusion)
    metadata.setdefault("run_attempt", args.attempt)
    if args.base_sha and not metadata.get("pull_requests"):
        metadata["pull_requests"] = [{"base": {"sha": args.base_sha}}]
    return metadata


def _load_local_bundle(args: argparse.Namespace) -> list[dict[str, object]]:
    if args.jobs_json is None:
        raise ValueError("--jobs-json is required unless --run-id is set")
    payload = json.loads(args.jobs_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        payload = {"jobs": payload}
    metadata = _local_metadata(args, payload)
    if isinstance(payload.get("attempts"), list):
        return [{"metadata": metadata, "attempts": payload["attempts"], "attempt": metadata.get("run_attempt")}]
    previous = _read_job_list(args.previous_jobs_json) if args.previous_jobs_json else None
    jobs = payload.get("jobs", payload)
    if not isinstance(jobs, list):
        raise ValueError("jobs JSON must be a list or an object with jobs")
    return [{
        "metadata": metadata,
        "jobs": [row for row in jobs if isinstance(row, dict)],
        "previous_jobs": previous,
        "attempt": args.attempt,
        "checkout_sha": payload.get("checkout_sha"),
        "source_sha": args.source_sha,
    }]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository")
    parser.add_argument("--run-id", action="append", type=int, dest="run_ids", default=[])
    parser.add_argument("--required-check", action="append", default=[])
    parser.add_argument("--jobs-json", type=Path)
    parser.add_argument("--previous-jobs-json", type=Path)
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--workflow-name")
    parser.add_argument("--event")
    parser.add_argument("--source-sha")
    parser.add_argument("--base-sha")
    parser.add_argument("--run-conclusion")
    parser.add_argument("--audit-log", action="append", type=Path, default=[])
    parser.add_argument("--qualification-log", action="append", type=Path, default=[])
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    return parser.parse_args()


def _empty_report(reason: str) -> dict[str, object]:
    return {
        "subject": {
            "repository": None,
            "event": None,
            "source_sha": None,
            "checkout_shas": [],
            "base_sha": None,
        },
        "identity_complete": False,
        "workflows": [],
        "runner_execution": {
            "complete": False,
            "known_minutes": 0,
            "known_partial": True,
            "by_platform": {},
            "by_conclusion": {
                "success": 0, "failure": 0, "timed_out": 0, "cancelled": 0, "other": 0,
            },
        },
        "required_gate_wait": {
            "complete": False,
            "trigger_created_at": None,
            "first_workflow_started_at": None,
            "last_required_check_completed_at": None,
            "elapsed_from_created_s": None,
            "elapsed_from_started_s": None,
            "missing_checks": [],
            "required_checks": [],
            "required_check_source": "explicit_cli",
            "workflow_time_errors": [],
        },
        "audit_lanes": [],
        "audit_run": None,
        "android_phases": [],
        "cancellations": [],
        "incomplete_reasons": [reason],
        "complete": False,
        "unit": "raw runner execution seconds / 60, not billed minutes",
    }


def _collect_file_evidence(
    args: argparse.Namespace,
) -> tuple[list[tuple[str, str]], list[dict[str, object]], dict[str, object] | None, list[str]]:
    qualification: list[tuple[str, str]] = []
    audit_lanes: list[dict[str, object]] = []
    markers: list[dict[str, object]] = []
    errors: list[str] = []
    try:
        for path in args.audit_log:
            text = path.read_text(encoding="utf-8")
            audit_lanes.extend(parse_audit_lane_timing(text))
            markers.extend(parse_audit_run_markers(text))
    except _LOAD_CATCH as exc:
        errors.append(f"audit lane timing unavailable: {exc}")
    audit_run, run_errors = _resolve_audit_run(markers)
    errors.extend(run_errors)
    try:
        for path in args.qualification_log:
            parsed = parse_qualification_log(path.read_text(encoding="utf-8"))
            if parsed:
                qualification.append(parsed)
    except _LOAD_CATCH as exc:
        errors.append(f"qualification log unavailable: {exc}")
    return qualification, audit_lanes, audit_run, errors


def main() -> int:
    args = _parse_args()
    summary: dict[str, object] | None = None
    try:
        remote = bool(args.run_ids) and args.jobs_json is None
        bundles = _load_remote_bundles(args) if remote else _load_local_bundle(args)
    except _LOAD_CATCH as exc:
        print(f"CI RUN TIMING INCOMPLETE: {exc}", file=sys.stderr)
        summary = _empty_report(str(exc))
        rendered = render_timing(summary)
        print(rendered, end="")
        _write_outputs(summary, rendered, args)
        return 2
    qualification, audit_lanes, audit_run, evidence_errors = _collect_file_evidence(args)
    if remote:
        token = _token()
        repository = args.repository or os.environ.get("GITHUB_REPOSITORY")
        if token and repository:
            try:
                extra_q, extra_a, extra_run, extra_errors = attach_remote_evidence(
                    bundles, repository, token,
                )
                qualification.extend(extra_q)
                audit_lanes.extend(extra_a)
                evidence_errors.extend(extra_errors)
                if extra_run is not None:
                    audit_run = extra_run
            except _LOAD_CATCH as exc:
                evidence_errors.append(str(exc))
    summary = build_report(
        bundles,
        repository=args.repository or os.environ.get("GITHUB_REPOSITORY"),
        required_checks=list(args.required_check or []),
        audit_lanes=audit_lanes,
        qualification=qualification,
        audit_run=audit_run,
        evidence_errors=evidence_errors,
    )
    rendered = render_timing(summary)
    print(rendered, end="")
    _write_outputs(summary, rendered, args)
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

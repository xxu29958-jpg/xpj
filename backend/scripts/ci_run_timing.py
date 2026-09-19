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
_AUDIT_LANE = re.compile(r"^AUDIT_LANE_TIMING\s+(\{.*\})\s*$")
_LOAD_CATCH = (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, urllib.error.URLError)

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


def parse_audit_lane_timing(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        match = _AUDIT_LANE.match(line.strip())
        if match is None:
            continue
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError("audit lane timing JSON is invalid") from exc
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _run_is_finished(metadata: dict) -> bool:
    return metadata.get("status") == "completed"


def _named_step(jobs: list[dict], name: str) -> dict | None:
    for job in jobs:
        for step in job.get("steps") or []:
            if isinstance(step, dict) and step.get("name") == name:
                return step
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


def android_phases_from_jobs(jobs: list[dict]) -> list[dict[str, object]]:
    configuration = {
        "name": "configuration",
        "phase": "configuration",
        **_derived_span(jobs, "Set up Java", "Accept Android SDK licenses"),
    }
    return [
        configuration,
        _phase_row("compile", "compile", "direct", _named_step(jobs, "Precompile connected APKs")),
        {
            "name": "cache_state",
            "phase": "cache",
            "measurement_kind": "unknown",
            "elapsed_s": None,
            "source_step": "Set up Gradle",
        },
        _phase_row(
            "emulator_prepare_install_test_exit",
            "emulator_prepare + install + test + exit",
            "combined",
            _named_step(jobs, "Run connected test"),
        ),
        _phase_row(
            "checkout_qualification",
            "checkout qualification",
            "direct",
            _named_step(jobs, "Verify qualification SHA"),
        ),
        _phase_row(
            "result_qualification",
            "result qualification",
            "direct",
            _named_step(jobs, "Enforce Connected result"),
        ),
    ]


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
    missing = [name for name in required_checks if name not in completed]
    last = max(completed.values()) if completed else None
    first_created = min(created) if created else None
    first_started = min(started) if started else None
    return {
        "complete": bool(required_checks) and not missing and first_created is not None and last is not None,
        "trigger_created_at": _utc_text(first_created),
        "first_workflow_started_at": _utc_text(first_started),
        "last_required_check_completed_at": _utc_text(last),
        "elapsed_from_created_s": _seconds(first_created, last),
        "elapsed_from_started_s": _seconds(first_started, last),
        "missing_checks": missing,
    }


def _unique_meta(bundles: list[dict[str, object]], key: str) -> set[object]:
    values = {bundle.get("metadata", {}).get(key) for bundle in bundles}
    values.discard(None)
    return values


def _base_shas(bundles: list[dict[str, object]]) -> set[str]:
    bases: set[str] = set()
    for bundle in bundles:
        for pull in bundle.get("metadata", {}).get("pull_requests") or []:
            if isinstance(pull, dict) and (pull.get("base") or {}).get("sha"):
                bases.add(str((pull.get("base") or {}).get("sha")))
    return bases


def _choose_source(heads: set[object], qualification: list[tuple[str, str]]) -> object:
    log_sources = {item[1] for item in qualification}
    if len(log_sources) == 1:
        return next(iter(log_sources))
    if len(heads) == 1:
        return next(iter(heads))
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
    events = _unique_meta(bundles, "event")
    heads = _unique_meta(bundles, "head_sha")
    bases = _base_shas(bundles)
    source = _choose_source(heads, qualification)
    event = next(iter(events)) if len(events) == 1 else None
    base = next(iter(bases)) if len(bases) == 1 else None
    checkouts = [item[0] for item in qualification]
    checkouts.extend(sha for sha in (_bundle_checkout(bundle) for bundle in bundles) if sha)
    if not source:
        notes.append("missing source_sha")
    if not checkouts:
        notes.append("missing checkout SHA")
    if event == "pull_request" and not base:
        notes.append("missing base_sha")
    if len(heads) > 1:
        notes.append("mixed source_sha across runs")
    return (
        {
            "repository": repository,
            "event": event,
            "source_sha": source,
            "checkout_shas": list(dict.fromkeys(checkouts)),
            "base_sha": base,
        },
        not notes,
        notes,
    )


def _final_job_completed_at(bundle: dict[str, object]) -> str | None:
    ended = [parse_utc(job.get("completed_at")) for job in _iter_bundle_jobs(bundle)]
    present = [item for item in ended if item is not None]
    return _utc_text(max(present)) if present else None


def _attempt_row(summary: dict[str, object]) -> dict[str, object]:
    inherited = sum(1 for job in summary.get("jobs") or [] if job.get("inherited"))
    return {
        "attempt": summary["attempt"],
        "actual_execution_minutes": summary["runner_execution_minutes"],
        "inherited_job_count": inherited,
        "complete": summary["complete"],
        "by_platform": summary["by_platform"],
        "by_conclusion": summary["by_conclusion"],
        "incomplete": summary["incomplete"],
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
        totals["android_jobs"].extend(_iter_bundle_jobs(bundle))


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
    totals["incomplete"].extend(_attempt_gap_notes(bundle))
    _note_special_workflow(bundle, metadata, total_minutes, run_id, totals)
    totals["workflows"].append(_workflow_row(bundle, metadata, run_id, attempt_rows, latest, total_minutes))


def _wait_notes(wait: dict[str, object], required_checks: list[str]) -> list[str]:
    if not required_checks:
        return ["required-check set not supplied"]
    if wait["complete"]:
        return []
    if wait["missing_checks"]:
        return [f"missing required checks: {', '.join(wait['missing_checks'])}"]
    return ["required-check wait is incomplete"]


def _backend_contracts_executed(bundles: list[dict[str, object]]) -> bool:
    for bundle in bundles:
        for job in _iter_bundle_jobs(bundle):
            if job.get("name") == "Backend contracts" and job.get("conclusion") in _EXECUTED_STEP:
                return True
    return False


def _audit_lanes_complete(audit_lanes: list[dict[str, object]]) -> bool:
    if not audit_lanes:
        return False
    return all(lane.get("returncode") is not None and lane.get("complete") is not False for lane in audit_lanes)


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
    if _backend_contracts_executed(bundles) and not _audit_lanes_complete(audit_lanes):
        notes.append("audit lane timing unavailable")
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
        "android_jobs": [],
        "known": 0.0,
        "runner_complete": True,
    }
    for bundle in bundles:
        _add_bundle(bundle, totals)
    pairs = list(qualification or [])
    if len(pairs) == 1:
        checkout, source = pairs[0]
        for bundle in bundles:
            bundle.setdefault("checkout_sha", checkout)
            bundle.setdefault("source_sha", source)
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
            "by_platform": totals["platforms"],
            "by_conclusion": totals["conclusions"],
        },
        "required_gate_wait": wait,
        "audit_lanes": list(audit_lanes or []),
        "android_phases": android_phases_from_jobs(list(totals["android_jobs"])),
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
) -> tuple[list[tuple[str, str]], list[dict[str, object]], list[str]]:
    qualification: list[tuple[str, str]] = []
    audit_lanes: list[dict[str, object]] = []
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
            bundle["source_sha"] = parsed[1]
            qualification.append(parsed)
        for job_name in _AUDIT_LOG_JOBS.get(workflow, ()):
            job = _find_named_job(bundle, job_name)
            if job is None:
                continue
            try:
                text = fetch_job_logs(repository, int(job["id"]), token, urlopen=urlopen)
                audit_lanes.extend(parse_audit_lane_timing(text))
            except _LOAD_CATCH:
                errors.append("audit lane timing unavailable")
    return qualification, audit_lanes, errors


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
        },
        "audit_lanes": [],
        "android_phases": [],
        "cancellations": [],
        "incomplete_reasons": [reason],
        "complete": False,
        "unit": "raw runner execution seconds / 60, not billed minutes",
    }


def _collect_file_evidence(args: argparse.Namespace) -> tuple[list[tuple[str, str]], list[dict[str, object]], list[str]]:
    qualification: list[tuple[str, str]] = []
    audit_lanes: list[dict[str, object]] = []
    errors: list[str] = []
    try:
        for path in args.audit_log:
            audit_lanes.extend(parse_audit_lane_timing(path.read_text(encoding="utf-8")))
    except _LOAD_CATCH as exc:
        errors.append(f"audit lane timing unavailable: {exc}")
    try:
        for path in args.qualification_log:
            parsed = parse_qualification_log(path.read_text(encoding="utf-8"))
            if parsed:
                qualification.append(parsed)
    except _LOAD_CATCH as exc:
        errors.append(f"qualification log unavailable: {exc}")
    return qualification, audit_lanes, errors


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
    qualification, audit_lanes, evidence_errors = _collect_file_evidence(args)
    if remote:
        token = _token()
        repository = args.repository or os.environ.get("GITHUB_REPOSITORY")
        if token and repository:
            try:
                extra_q, extra_a, extra_errors = attach_remote_evidence(
                    bundles, repository, token,
                )
                qualification.extend(extra_q)
                audit_lanes.extend(extra_a)
                evidence_errors.extend(extra_errors)
            except _LOAD_CATCH as exc:
                evidence_errors.append(str(exc))
    summary = build_report(
        bundles,
        repository=args.repository or os.environ.get("GITHUB_REPOSITORY"),
        required_checks=list(args.required_check or []),
        audit_lanes=audit_lanes,
        qualification=qualification,
        evidence_errors=evidence_errors,
    )
    rendered = render_timing(summary)
    print(rendered, end="")
    _write_outputs(summary, rendered, args)
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

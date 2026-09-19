"""One-shot timing summary for already-finished GitHub Actions job pages."""

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
IDENTITY_ARTIFACT = "ci-run-identity"
INNER_ARTIFACT = "connected-inner-timing"
IDENTITY_UNAVAILABLE = "target run identity artifact unavailable"
CONNECTED_JOB_NAME = "Connected execution"
CONNECTED_STEP_NAME = "Run connected test"
_IDENTITY_CATCH = (
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
OBSERVER_JOB_NAME = "CI run timing"
OBSERVER_EXCLUSION = "CI run timing observer itself"

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
        _bill_row(row, job.get("conclusion"), buckets)
        _record_interval(job, starts, ends)


def _split_observer_jobs(
    jobs: list[dict],
    exclude_job_names: tuple[str, ...],
) -> tuple[list[dict], list[str]]:
    visible = [job for job in jobs if isinstance(job, dict)]
    if not exclude_job_names:
        return visible, []
    kept = [job for job in visible if job.get("name") not in exclude_job_names]
    exclusions = [
        OBSERVER_EXCLUSION if name == OBSERVER_JOB_NAME else f"{name} observer itself"
        for name in exclude_job_names
    ]
    return kept, exclusions


def _timing_identity(
    *,
    repository: str | None,
    workflow: str | None,
    run_id: object,
    run_attempt: object,
    event: str | None,
    source_sha: str | None,
    measurement_sha: str | None,
    base_sha: str | None = None,
    job: str | None = None,
    outer_step: str | None = None,
) -> dict[str, object]:
    identity: dict[str, object] = {
        "repository": repository,
        "workflow": workflow,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "event": event,
        "base_sha": base_sha,
        "source_sha": source_sha,
        "measurement_sha": measurement_sha,
    }
    if job:
        identity["job"] = job
    if outer_step:
        identity["outer_step"] = outer_step
    return identity


def summarize_jobs(
    jobs: list[dict],
    *,
    attempt: int | None = None,
    previous_jobs: list[dict] | None = None,
    exclude_job_names: tuple[str, ...] = (),
    report_identity: dict[str, object] | None = None,
    run_conclusion: str | None = None,
) -> dict[str, object]:
    visible, exclusions = _split_observer_jobs(jobs, exclude_job_names)
    identity = _shared_identity(visible)
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
    for job in visible:
        row = job_timing(job, inherited=_claim_inherited(job, unused))
        status = _status_for(job, row, attempt)
        row["timing_status"] = status
        _apply_status(
            job, row, status, identity, incomplete, skipped, buckets, starts, ends, previous_notes,
        )
        timed.append(row)
    total = sum(buckets.values())
    step_incomplete = any(row.get("timing_status") in _STEP_DETAIL for row in timed)
    payload = {
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
        "run_conclusion": run_conclusion,
        "wasted_execution_minutes": round(total / 60, 3) if run_conclusion == "cancelled" else 0.0,
        "skipped_jobs": skipped,
        "observed_subset_wall_clock_s": _seconds(min(starts), max(ends)) if starts and ends else None,
        "coverage": "observed subset of supplied jobs only; not the final required-check wait",
        "coverage_exclusions": exclusions,
        "incomplete": incomplete,
        "step_timing_complete": not step_incomplete,
        "complete": not incomplete,
        "unit": "raw runner execution seconds / 60, not billed minutes",
    }
    _apply_identity_notes(payload, report_identity, identity, attempt)
    return payload


def _apply_identity_notes(
    payload: dict[str, object],
    report_identity: dict[str, object] | None,
    job_identity: dict[str, object],
    attempt: int | None,
) -> None:
    notes = _identity_notes(report_identity, job_identity, attempt)
    if report_identity:
        payload["identity"] = report_identity
    payload["identity_complete"] = bool(report_identity) and not notes
    if not notes:
        return
    payload["incomplete"] = list(payload["incomplete"]) + notes
    payload["complete"] = False
    if report_identity and report_identity.get("identity_unavailable"):
        payload["reason"] = str(report_identity["identity_unavailable"])


def _ids_equal(left: object, right: object) -> bool:
    if left in {None, ""} or right in {None, ""}:
        return True
    return str(left) == str(right)


def _identity_notes(
    report_identity: dict[str, object] | None,
    job_identity: dict[str, object],
    attempt: int | None,
) -> list[str]:
    if not report_identity:
        return []
    notes: list[str] = []
    if report_identity.get("identity_unavailable"):
        notes.append(str(report_identity["identity_unavailable"]))
        return notes
    required = [
        "repository", "workflow", "run_id", "run_attempt", "event", "source_sha", "measurement_sha",
    ]
    if report_identity.get("event") == "pull_request":
        required.append("base_sha")
    missing = [key for key in required if report_identity.get(key) in {None, ""}]
    if missing:
        notes.append(f"missing timing identity ({', '.join(missing)})")
        return notes
    checks = (
        ("run_id", report_identity.get("run_id"), job_identity.get("run_id")),
        ("workflow", report_identity.get("workflow"), job_identity.get("workflow_name")),
        ("run_attempt", report_identity.get("run_attempt"), attempt),
        ("source_sha", report_identity.get("source_sha"), job_identity.get("head_sha")),
    )
    for name, left, right in checks:
        if not _ids_equal(left, right):
            notes.append(f"identity {name} mismatch: {left} != {right}")
    if (
        report_identity.get("event") == "pull_request"
        and report_identity.get("source_sha") == report_identity.get("measurement_sha")
    ):
        notes.append("pull_request measurement_sha must differ from source_sha")
    return notes


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
        f"step_timing_complete={summary.get('step_timing_complete')}",
        f"identity_complete={summary.get('identity_complete')}",
        f"coverage_exclusions={summary.get('coverage_exclusions')}",
        f"run_conclusion={summary.get('run_conclusion')}",
        f"reason={summary.get('reason')}",
    ]
    identity = summary.get("identity")
    if isinstance(identity, dict):
        lines.append(
            "identity "
            f"repository={identity.get('repository')} workflow={identity.get('workflow')} "
            f"run_id={identity.get('run_id')} run_attempt={identity.get('run_attempt')} "
            f"event={identity.get('event')} base_sha={identity.get('base_sha')} "
            f"source_sha={identity.get('source_sha')} "
            f"measurement_sha={identity.get('measurement_sha')}"
        )
    lines.extend([
        f"runner_execution_minutes={summary['runner_execution_minutes']} ({summary['unit']})",
        f"total_execution_minutes={summary['total_execution_minutes']}",
        f"success_execution_minutes={summary['success_execution_minutes']}",
        f"failure_execution_minutes={summary['failure_execution_minutes']}",
        f"cancelled_execution_minutes={summary['cancelled_execution_minutes']}",
        f"wasted_execution_minutes={summary.get('wasted_execution_minutes')}",
        f"neutral_execution_minutes={summary['neutral_execution_minutes']}",
        f"other_execution_minutes={summary['other_execution_minutes']}",
        f"skipped_jobs={len(skipped)}",
        f"observed_subset_wall_clock_s={summary['observed_subset_wall_clock_s']}",
        f"coverage: {summary['coverage']}",
    ])
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


def _github_json(url: str, token: str, *, urlopen=urllib.request.urlopen) -> dict:
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
    if not isinstance(payload, dict):
        raise ValueError("GitHub JSON object required")
    return payload


def parse_qualification_log(text: str) -> tuple[str, str] | None:
    match = _QUALIFICATION_LOG.search(text)
    if match is None:
        return None
    return match.group(1), match.group(2)


def write_scope_identity(path: Path, identity: dict[str, object]) -> dict[str, object]:
    payload = {
        "repository": identity.get("repository"),
        "workflow": identity.get("workflow"),
        "run_id": identity.get("run_id"),
        "run_attempt": identity.get("run_attempt"),
        "event": identity.get("event"),
        "base_sha": identity.get("base_sha"),
        "source_sha": identity.get("source_sha"),
        "measurement_sha": identity.get("measurement_sha"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def cross_check_live_merge_ref(
    repository: str,
    number: int,
    identity: dict[str, object],
    token: str,
    *,
    urlopen=urllib.request.urlopen,
) -> str:
    ref = _github_json(
        f"{_GITHUB_API}/repos/{repository}/git/ref/pull/{number}/merge",
        token,
        urlopen=urlopen,
    )
    live = (ref.get("object") or {}).get("sha") if isinstance(ref.get("object"), dict) else None
    if not live:
        return "unavailable"
    commit = _github_json(
        f"{_GITHUB_API}/repos/{repository}/git/commits/{live}",
        token,
        urlopen=urlopen,
    )
    parents = [
        item.get("sha") for item in (commit.get("parents") or [])
        if isinstance(item, dict) and item.get("sha")
    ]
    source = identity.get("source_sha")
    base = identity.get("base_sha")
    if len(parents) == 2 and source in parents and base in parents:
        return "matches"
    return "stale_or_mismatch"


def load_run_artifact(
    repository: str,
    run_id: int,
    token: str,
    name: str,
    *,
    urlopen=None,
) -> dict[str, object] | None:
    opener = urlopen or urllib.request.urlopen
    listing = _github_json(
        f"{_GITHUB_API}/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
        token,
        urlopen=opener,
    )
    artifact = next(
        (
            row for row in (listing.get("artifacts") or [])
            if isinstance(row, dict) and row.get("name") == name and not row.get("expired")
        ),
        None,
    )
    if not artifact or not artifact.get("archive_download_url"):
        return None
    request = urllib.request.Request(
        str(artifact["archive_download_url"]),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ticketbox-ci-run-timing",
        },
    )
    with opener(request) as response:
        blob = response.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        member = next((item for item in archive.namelist() if item.endswith(".json")), None)
        if member is None:
            return None
        payload = json.loads(archive.read(member).decode("utf-8"))
    return payload if isinstance(payload, dict) else None


def load_identity_artifact(
    repository: str,
    run_id: int,
    token: str,
    *,
    urlopen=urllib.request.urlopen,
) -> dict[str, object] | None:
    return load_run_artifact(repository, run_id, token, IDENTITY_ARTIFACT, urlopen=urlopen)


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


def _fallback_measurement_sha(args: argparse.Namespace) -> str | None:
    explicit = args.measurement_sha or os.environ.get("XPJ_WEIGHT_MEASUREMENT_SHA")
    if explicit or args.from_run_identity or args.run_identity_json:
        return explicit
    return os.environ.get("GITHUB_SHA")


def _cli_identity(args: argparse.Namespace, attempt: int | None, jobs: list[dict]) -> dict[str, object]:
    shared = _shared_identity(jobs)
    return _timing_identity(
        repository=args.github_repository or os.environ.get("GITHUB_REPOSITORY"),
        workflow=args.workflow_name or os.environ.get("XPJ_TIMING_WORKFLOW") or shared.get("workflow_name"),
        run_id=args.github_run_id or os.environ.get("GITHUB_RUN_ID") or shared.get("run_id"),
        run_attempt=attempt,
        event=args.event or os.environ.get("XPJ_WEIGHT_EVENT") or os.environ.get("GITHUB_EVENT_NAME"),
        base_sha=args.base_sha or os.environ.get("XPJ_WEIGHT_BASE_SHA"),
        source_sha=args.source_sha or os.environ.get("XPJ_WEIGHT_SOURCE_SHA"),
        measurement_sha=_fallback_measurement_sha(args),
        job=args.job_name,
        outer_step=args.outer_step,
    )


def stamp_connected_inner(
    path: Path,
    identity: dict[str, object],
    *,
    state: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
    if state:
        payload["state"] = state
    if reason:
        payload["reason"] = reason
    incomplete: list[str] = []
    if payload.get("elapsed_s") is None:
        payload.setdefault("state", state or "started")
        payload.setdefault("reason", reason or "inner Gradle timing not finalized")
        incomplete.append(str(payload["reason"]))
    else:
        payload["state"] = "finalized"
        payload["reason"] = None
    payload["kind"] = payload.get("kind") or "gradle_connected_test"
    payload["identity"] = identity
    payload["job"] = identity.get("job") or "Connected execution"
    payload["outer_step"] = identity.get("outer_step") or "Run connected test"
    payload["incomplete"] = incomplete
    payload["complete"] = not incomplete
    payload.setdefault("not", "emulator/action overhead residual lives outside this interval")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-json", type=Path)
    parser.add_argument("--previous-jobs-json", type=Path)
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--from-github", action="store_true")
    parser.add_argument("--from-run-identity", action="store_true")
    parser.add_argument("--run-identity-json", type=Path)
    parser.add_argument("--write-identity-json", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--derive-cancelled-inner", action="store_true")
    parser.add_argument("--run-conclusion")
    parser.add_argument("--github-repository")
    parser.add_argument("--github-run-id", type=int)
    parser.add_argument("--exclude-job-name", action="append", default=[])
    parser.add_argument("--source-sha")
    parser.add_argument("--measurement-sha")
    parser.add_argument("--base-sha")
    parser.add_argument("--event")
    parser.add_argument("--workflow-name")
    parser.add_argument("--job-name")
    parser.add_argument("--outer-step")
    parser.add_argument("--inner-state")
    parser.add_argument("--inner-reason")
    parser.add_argument("--stamp-connected-inner", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--summary", type=Path, default=os.environ.get("GITHUB_STEP_SUMMARY"))
    return parser.parse_args()


def _run_stamp(args: argparse.Namespace) -> int:
    if args.derive_cancelled_inner:
        return _run_cancelled_inner(args)
    identity = _cli_identity(args, args.attempt, [])
    payload = stamp_connected_inner(
        args.stamp_connected_inner,
        identity,
        state=args.inner_state,
        reason=args.inner_reason,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["complete"] or args.allow_partial:
        return 0
    return 2


def _run_write_identity(args: argparse.Namespace) -> int:
    identity = _cli_identity(args, args.attempt, [])
    payload = write_scope_identity(args.write_identity_json, identity)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _load_jobs(args: argparse.Namespace) -> tuple[list[dict], list[dict] | None, int | None]:
    if args.from_github:
        return _load_github_pair(args)
    if args.jobs_json is None:
        raise ValueError("--jobs-json is required unless --from-github is set")
    previous = _read_job_list(args.previous_jobs_json) if args.previous_jobs_json else None
    return _read_job_list(args.jobs_json), previous, args.attempt


def _failed_summary(reason: str) -> dict[str, object]:
    return {
        "attempt": None,
        "run_id": None,
        "workflow_name": None,
        "head_sha": None,
        "jobs": [],
        "runner_execution_minutes": 0,
        "total_execution_minutes": 0,
        "success_execution_minutes": 0,
        "failure_execution_minutes": 0,
        "cancelled_consumed_minutes": 0,
        "cancelled_execution_minutes": 0,
        "neutral_execution_minutes": 0,
        "other_execution_minutes": 0,
        "run_conclusion": None,
        "wasted_execution_minutes": 0.0,
        "skipped_jobs": [],
        "observed_subset_wall_clock_s": None,
        "coverage": "observed subset of supplied jobs only; not the final required-check wait",
        "coverage_exclusions": [],
        "incomplete": [reason],
        "step_timing_complete": False,
        "identity_complete": False,
        "complete": False,
        "reason": reason,
        "unit": "raw runner execution seconds / 60, not billed minutes",
    }


def _merge_identity(base: dict[str, object], loaded: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key in (
        "repository", "workflow", "run_id", "run_attempt", "event",
        "base_sha", "source_sha", "measurement_sha",
    ):
        if loaded.get(key) not in {None, ""}:
            merged[key] = loaded[key]
    return merged


def _identity_from_file(path: Path) -> dict[str, object] | None:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def _artifact_from_observed_run(args: argparse.Namespace, name: str) -> dict[str, object] | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repository = args.github_repository or os.environ.get("GITHUB_REPOSITORY")
    run_id = args.github_run_id or os.environ.get("GITHUB_RUN_ID")
    if not (token and repository and run_id):
        return None
    return load_run_artifact(repository, int(run_id), token, name)


def _identity_from_observed_run(args: argparse.Namespace) -> dict[str, object] | None:
    return _artifact_from_observed_run(args, IDENTITY_ARTIFACT)


def _required_identity_payload(args: argparse.Namespace) -> dict[str, object] | None:
    if args.run_identity_json:
        if not args.run_identity_json.exists():
            return None
        return _identity_from_file(args.run_identity_json)
    if args.from_run_identity:
        return _identity_from_observed_run(args)
    return None


def _mark_unavailable(identity: dict[str, object]) -> dict[str, object]:
    marked = dict(identity)
    marked["identity_unavailable"] = IDENTITY_UNAVAILABLE
    marked["measurement_sha"] = None
    return marked


def _strict_observed_identity(
    args: argparse.Namespace,
    identity: dict[str, object],
) -> dict[str, object]:
    try:
        loaded = _required_identity_payload(args)
    except _IDENTITY_CATCH:
        return _mark_unavailable(identity)
    if not loaded:
        return _mark_unavailable(identity)
    return _merge_identity(identity, loaded)


def _observed_identity(
    args: argparse.Namespace,
    jobs: list[dict],
    attempt: int | None,
) -> dict[str, object] | None:
    identity = _cli_identity(args, attempt, jobs)
    if args.from_run_identity or args.run_identity_json:
        return _strict_observed_identity(args, identity)
    if identity.get("source_sha") and identity.get("measurement_sha"):
        return identity
    return None


def _named_job(jobs: list[dict], name: str) -> dict | None:
    return next((job for job in jobs if isinstance(job, dict) and job.get("name") == name), None)


def _named_step(job: dict, name: str) -> dict | None:
    for step in job.get("steps") or []:
        if isinstance(step, dict) and step.get("name") == name:
            return step
    return None


def _never_started(row: dict | None) -> bool:
    if not row:
        return True
    if row.get("conclusion") == "skipped":
        return True
    return not row.get("started_at")


def derive_missing_inner_state(
    jobs: list[dict],
    *,
    job_name: str | None = None,
    step_name: str | None = None,
) -> tuple[str, str]:
    job = _named_job(jobs, job_name or CONNECTED_JOB_NAME)
    if job is None or _never_started(job):
        return "not_started", "connected execution did not start"
    step = _named_step(job, step_name or CONNECTED_STEP_NAME)
    if _never_started(step):
        return "not_started", "connected test step did not start"
    conclusion = step.get("conclusion") or job.get("conclusion")
    if conclusion in {"success", "failure"}:
        return "finished_but_artifact_missing", "connected test finished but inner timing artifact missing"
    if conclusion == "cancelled":
        return "cancelled_during_connected", "connected test cancelled after start"
    return "unknown", "connected inner timing artifact missing with inconclusive job evidence"


def _jobs_or_empty(args: argparse.Namespace) -> tuple[list[dict], bool]:
    try:
        jobs, _previous, _attempt = _load_jobs(args)
    except _IDENTITY_CATCH:
        return [], False
    return jobs, True


def _retained_inner_payload(args: argparse.Namespace) -> dict[str, object] | None:
    try:
        return _artifact_from_observed_run(args, INNER_ARTIFACT)
    except _IDENTITY_CATCH:
        return None


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _stamp_cancelled_inner(args: argparse.Namespace) -> int:
    jobs, fetched = _jobs_or_empty(args)
    identity = _strict_observed_identity(args, _cli_identity(args, args.attempt, jobs))
    retained = _retained_inner_payload(args)
    if retained is not None:
        args.stamp_connected_inner.write_text(
            json.dumps(retained, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        _print_json(retained)
        return 0
    if fetched:
        state, reason = derive_missing_inner_state(
            jobs, job_name=args.job_name, step_name=args.outer_step,
        )
    else:
        state, reason = "unknown", "target run jobs unavailable"
    _print_json(stamp_connected_inner(
        args.stamp_connected_inner, identity, state=state, reason=reason,
    ))
    return 0


def _run_cancelled_inner(args: argparse.Namespace) -> int:
    try:
        return _stamp_cancelled_inner(args)
    except _IDENTITY_CATCH as exc:
        identity = _mark_unavailable(_cli_identity(args, args.attempt, []))
        _print_json(stamp_connected_inner(
            args.stamp_connected_inner, identity, state="unknown", reason=str(exc),
        ))
        return 0


def main() -> int:
    args = _parse_args()
    summary: dict[str, object] | None = None
    try:
        if args.write_identity_json:
            return _run_write_identity(args)
        if args.stamp_connected_inner:
            return _run_stamp(args)
        jobs, previous, attempt = _load_jobs(args)
        visible, _exclusions = _split_observer_jobs(jobs, tuple(args.exclude_job_name))
        summary = summarize_jobs(
            jobs,
            attempt=attempt,
            previous_jobs=previous,
            exclude_job_names=tuple(args.exclude_job_name),
            report_identity=_observed_identity(args, visible, attempt),
            run_conclusion=args.run_conclusion or os.environ.get("XPJ_TIMING_RUN_CONCLUSION"),
        )
    except _IDENTITY_CATCH as exc:
        print(f"CI RUN TIMING INCOMPLETE: {exc}", file=sys.stderr)
        if summary is None:
            summary = _failed_summary(str(exc))
    rendered = render_timing(summary)
    print(rendered, end="")
    _write_outputs(summary, rendered, args)
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_SAFE_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_SAFE_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
_TRUSTED_EVENTS = frozenset({"schedule", "workflow_dispatch"})
_WORKFLOW_PATH = ".github/workflows/android-nvd-cache.yml"
_API_VERSION = "2022-11-28"
_ARTIFACT_LOOKBACK_DAYS = 4
_MAX_RUN_PAGES = 10


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _request_json(url: str, *, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "xpj-android-nvd-artifact-selector",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return _mapping(
            json.load(response),
            label=f"GitHub API response for {url}",
        )


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _trusted_run(
    raw_run: object,
    *,
    repository: str,
    default_branch: str,
) -> dict[str, Any] | None:
    run = _mapping(raw_run, label="workflow run")
    head_repository = run.get("head_repository")
    if not isinstance(head_repository, dict):
        return None
    if (
        run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("head_branch") != default_branch
        or run.get("event") not in _TRUSTED_EVENTS
        or run.get("path") != _WORKFLOW_PATH
        or head_repository.get("full_name") != repository
    ):
        return None
    run_id = run.get("id")
    run_attempt = run.get("run_attempt")
    if (
        isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id <= 0
        or isinstance(run_attempt, bool)
        or not isinstance(run_attempt, int)
        or run_attempt <= 0
    ):
        raise ValueError("trusted workflow run has an invalid identity")
    return run


def _artifact_attempt(
    *,
    artifact_name: object,
    artifact_prefix: str,
    run_id: int,
) -> int | None:
    if not isinstance(artifact_name, str):
        return None
    match = re.fullmatch(
        rf"{re.escape(artifact_prefix)}{run_id}-([1-9][0-9]*)",
        artifact_name,
    )
    return int(match.group(1)) if match is not None else None


def select_artifact(
    *,
    runs: list[object],
    artifacts_by_run: dict[int, list[object]],
    repository: str,
    default_branch: str,
    artifact_prefix: str,
) -> tuple[int, str, int, str] | None:
    candidates: list[tuple[datetime, int, int, int, str, str]] = []
    identities: set[tuple[int, str]] = set()
    for raw_run in runs:
        run = _trusted_run(
            raw_run,
            repository=repository,
            default_branch=default_branch,
        )
        if run is None:
            continue
        run_id = run["id"]
        for raw_artifact in artifacts_by_run.get(run_id, []):
            artifact = _mapping(raw_artifact, label="workflow artifact")
            artifact_name = artifact.get("name")
            attempt = _artifact_attempt(
                artifact_name=artifact_name,
                artifact_prefix=artifact_prefix,
                run_id=run_id,
            )
            if attempt is None:
                continue
            identity = (run_id, artifact_name)
            if identity in identities:
                raise ValueError("trusted workflow run has duplicate NVD artifacts")
            identities.add(identity)
            if artifact.get("expired") is True:
                continue
            if artifact.get("expired") is not False or attempt > run["run_attempt"]:
                raise ValueError("trusted NVD artifact has an invalid attempt")
            artifact_id = artifact.get("id")
            digest = artifact.get("digest")
            if (
                isinstance(artifact_id, bool)
                or not isinstance(artifact_id, int)
                or artifact_id <= 0
                or not isinstance(digest, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            ):
                raise ValueError("trusted NVD artifact has an invalid identity")
            created_at = _timestamp(
                artifact.get("created_at"),
                label="trusted NVD artifact created_at",
            )
            candidates.append(
                (
                    created_at,
                    attempt,
                    artifact_id,
                    run_id,
                    artifact_name,
                    digest,
                )
            )
    if not candidates:
        return None
    _, _, artifact_id, run_id, artifact_name, digest = max(candidates)
    return run_id, artifact_name, artifact_id, digest


def _write_outputs(output: Path, selected: tuple[int, str, int, str] | None) -> None:
    with output.open("a", encoding="utf-8", newline="\n") as stream:
        if selected is None:
            stream.write("found=false\n")
            return
        run_id, artifact_name, artifact_id, digest = selected
        stream.write("found=true\n")
        stream.write(f"run-id={run_id}\n")
        stream.write(f"artifact-name={artifact_name}\n")
        stream.write(f"artifact-id={artifact_id}\n")
        stream.write(f"artifact-digest={digest}\n")


def main() -> int:
    api_url = os.environ.get("GITHUB_API_URL", "").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    default_branch = os.environ.get("DEFAULT_BRANCH", "")
    workflow = os.environ.get("NVD_WORKFLOW", "")
    artifact_prefix = os.environ.get("NVD_ARTIFACT_PREFIX", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    output = os.environ.get("GITHUB_OUTPUT", "")
    if not api_url.startswith("https://"):
        raise ValueError("GitHub API URL must use HTTPS")
    if _SAFE_REPOSITORY.fullmatch(repository) is None:
        raise ValueError("GitHub repository identity is invalid")
    if _SAFE_BRANCH.fullmatch(default_branch) is None or ".." in default_branch:
        raise ValueError("default branch identity is invalid")
    if workflow != "android-nvd-cache.yml":
        raise ValueError("NVD producer workflow identity is invalid")
    if (
        not artifact_prefix.endswith("-")
        or _SAFE_ARTIFACT.fullmatch(artifact_prefix[:-1]) is None
    ):
        raise ValueError("NVD artifact prefix is invalid")
    if not token or not output:
        raise ValueError("GitHub token and output channel are required")

    owner_repo = urllib.parse.quote(repository, safe="/")
    workflow_id = urllib.parse.quote(workflow, safe="")
    created_after = datetime.now(UTC) - timedelta(days=_ARTIFACT_LOOKBACK_DAYS)
    created_filter = created_after.strftime("%Y-%m-%dT%H:%M:%SZ")
    runs: list[object] = []
    for page in range(1, _MAX_RUN_PAGES + 1):
        query = urllib.parse.urlencode(
            {
                "branch": default_branch,
                "status": "success",
                "created": f">={created_filter}",
                "per_page": 100,
                "page": page,
            }
        )
        runs_document = _request_json(
            f"{api_url}/repos/{owner_repo}/actions/workflows/"
            f"{workflow_id}/runs?{query}",
            token=token,
        )
        page_runs = runs_document.get("workflow_runs")
        if not isinstance(page_runs, list):
            raise ValueError("GitHub workflow-runs response is invalid")
        runs.extend(page_runs)
        if len(page_runs) < 100:
            break
    else:
        raise ValueError("GitHub workflow-runs result exceeded the trusted window")

    artifacts_by_run: dict[int, list[object]] = {}
    for raw_run in runs:
        run = _trusted_run(
            raw_run,
            repository=repository,
            default_branch=default_branch,
        )
        if run is None:
            continue
        run_id = run["id"]
        document = _request_json(
            f"{api_url}/repos/{owner_repo}/actions/runs/{run_id}/artifacts?per_page=100",
            token=token,
        )
        artifacts = document.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("GitHub artifacts response is invalid")
        artifacts_by_run[run_id] = artifacts
    selected = select_artifact(
        runs=runs,
        artifacts_by_run=artifacts_by_run,
        repository=repository,
        default_branch=default_branch,
        artifact_prefix=artifact_prefix,
    )
    _write_outputs(Path(output), selected)
    print("ANDROID_NVD_ARTIFACT_FOUND" if selected else "ANDROID_NVD_ARTIFACT_MISSING")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
        urllib.error.URLError,
    ) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

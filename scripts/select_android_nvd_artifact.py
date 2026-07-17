from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_SAFE_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_SAFE_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
_TRUSTED_EVENTS = frozenset({"schedule", "workflow_dispatch"})
_WORKFLOW_PATH = ".github/workflows/android-nvd-cache.yml"
_API_VERSION = "2022-11-28"


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


def select_artifact(
    *,
    runs: list[object],
    artifacts_by_run: dict[int, list[object]],
    repository: str,
    default_branch: str,
    artifact_prefix: str,
) -> tuple[int, str, int, str] | None:
    for raw_run in runs:
        run = _trusted_run(
            raw_run,
            repository=repository,
            default_branch=default_branch,
        )
        if run is None:
            continue
        run_id = run["id"]
        expected_name = f"{artifact_prefix}{run_id}-{run['run_attempt']}"
        matches = []
        for raw_artifact in artifacts_by_run.get(run_id, []):
            artifact = _mapping(raw_artifact, label="workflow artifact")
            if artifact.get("name") == expected_name and artifact.get("expired") is False:
                matches.append(artifact)
        if len(matches) > 1:
            raise ValueError("trusted workflow run has duplicate NVD artifacts")
        if not matches:
            continue
        artifact_id = matches[0].get("id")
        digest = matches[0].get("digest")
        if (
            isinstance(artifact_id, bool)
            or not isinstance(artifact_id, int)
            or artifact_id <= 0
            or not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("trusted NVD artifact has an invalid identity")
        return run_id, expected_name, artifact_id, digest
    return None


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
    query = urllib.parse.urlencode(
        {
            "branch": default_branch,
            "status": "success",
            "per_page": 20,
        }
    )
    runs_document = _request_json(
        f"{api_url}/repos/{owner_repo}/actions/workflows/{workflow_id}/runs?{query}",
        token=token,
    )
    runs = runs_document.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("GitHub workflow-runs response is invalid")
    selected = None
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
        selected = select_artifact(
            runs=[run],
            artifacts_by_run={run_id: artifacts},
            repository=repository,
            default_branch=default_branch,
            artifact_prefix=artifact_prefix,
        )
        if selected is not None:
            break
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

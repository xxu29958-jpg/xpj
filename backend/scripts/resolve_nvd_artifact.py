"""Resolve the newest immutable NVD artifact from a successful main run."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

API_VERSION = "2022-11-28"
TRUSTED_EVENTS = frozenset({"push", "schedule", "workflow_dispatch"})
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class ResolutionError(RuntimeError):
    """GitHub did not return a structurally trustworthy artifact reference."""


class ResourceNotFoundError(ResolutionError):
    """The producer workflow does not exist on main yet."""


JsonGetter = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class ArtifactReference:
    run_id: int
    artifact_id: int


def _github_json_getter(token: str) -> JsonGetter:
    def get_json(url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "ticketbox-ci",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ResourceNotFoundError(
                    "the NVD producer workflow was not found"
                ) from exc
            raise ResolutionError("GitHub Actions artifact lookup failed") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ResolutionError("GitHub Actions artifact lookup failed") from exc
        if not isinstance(payload, dict):
            raise ResolutionError("GitHub Actions returned a non-object response")
        return payload

    return get_json


def _trusted_run(
    run: object,
    *,
    repository: str,
    workflow_path: str,
    branch: str,
    now: datetime,
    max_age: timedelta,
) -> datetime | None:
    if not isinstance(run, dict):
        return None
    repo = run.get("repository")
    if not (
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("head_branch") == branch
        and run.get("event") in TRUSTED_EVENTS
        and run.get("path") == workflow_path
        and isinstance(repo, dict)
        and repo.get("full_name") == repository
        and type(run.get("id")) is int
        and run["id"] > 0
        and isinstance(run.get("head_sha"), str)
        and SHA_PATTERN.fullmatch(run["head_sha"]) is not None
    ):
        return None
    created_at = run.get("created_at")
    if not isinstance(created_at, str):
        return None
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if created.tzinfo is None:
        return None
    age = now - created.astimezone(UTC)
    if age < -timedelta(minutes=5) or age > max_age:
        return None
    return created


def _reference_from_run(
    run: dict[str, Any],
    *,
    encoded_repo: str,
    artifact_name: str,
    api_url: str,
    get_json: JsonGetter,
) -> ArtifactReference | None:
    run_id = run["id"]
    artifacts_url = (
        f"{api_url.rstrip('/')}/repos/{encoded_repo}/actions/runs/"
        f"{run_id}/artifacts?per_page=100"
    )
    artifacts = get_json(artifacts_url).get("artifacts")
    if not isinstance(artifacts, list):
        raise ResolutionError("GitHub Actions artifacts are missing")
    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("name") == artifact_name
        and artifact.get("expired") is False
    ]
    if len(matches) != 1:
        return None
    artifact = matches[0]
    workflow_run = artifact.get("workflow_run")
    artifact_id = artifact.get("id")
    digest = artifact.get("digest")
    if (
        type(artifact_id) is not int
        or artifact_id <= 0
        or not isinstance(digest, str)
        or DIGEST_PATTERN.fullmatch(digest) is None
        or not isinstance(workflow_run, dict)
        or workflow_run.get("id") != run_id
        or workflow_run.get("head_sha") != run["head_sha"]
    ):
        return None
    return ArtifactReference(
        run_id=run_id,
        artifact_id=artifact_id,
    )


def resolve_artifact(
    *,
    repository: str,
    workflow: str,
    branch: str,
    artifact_name: str,
    api_url: str,
    get_json: JsonGetter,
    now: datetime | None = None,
    max_age_hours: int = 48,
) -> ArtifactReference | None:
    if repository.count("/") != 1 or repository.strip("/") != repository:
        raise ResolutionError("repository must use owner/name form")
    if not workflow.endswith((".yml", ".yaml")) or "/" in workflow:
        raise ResolutionError("workflow must be a workflow file name")
    if not branch or not artifact_name or artifact_name.strip() != artifact_name:
        raise ResolutionError("branch and artifact name are required")
    if max_age_hours <= 0:
        raise ResolutionError("max artifact age must be positive")
    observed_at = now or datetime.now(UTC)
    if observed_at.tzinfo is None:
        raise ResolutionError("current time must include a timezone")
    encoded_repo = "/".join(
        urllib.parse.quote(part, safe="") for part in repository.split("/")
    )
    encoded_workflow = urllib.parse.quote(workflow, safe="")
    query = urllib.parse.urlencode(
        {
            "branch": branch,
            "status": "success",
            "exclude_pull_requests": "true",
            "per_page": "20",
        }
    )
    runs_url = (
        f"{api_url.rstrip('/')}/repos/{encoded_repo}/actions/workflows/"
        f"{encoded_workflow}/runs?{query}"
    )
    try:
        runs_payload = get_json(runs_url)
    except ResourceNotFoundError:
        return None
    runs = runs_payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ResolutionError("GitHub Actions workflow runs are missing")
    workflow_path = f".github/workflows/{workflow}"
    trusted_runs: list[tuple[datetime, dict[str, Any]]] = []
    for candidate in runs:
        created_at = _trusted_run(
            candidate,
            repository=repository,
            workflow_path=workflow_path,
            branch=branch,
            now=observed_at.astimezone(UTC),
            max_age=timedelta(hours=max_age_hours),
        )
        if created_at is not None and isinstance(candidate, dict):
            trusted_runs.append((created_at, candidate))
    trusted_runs.sort(key=lambda item: item[0], reverse=True)
    for _created_at, run in trusted_runs:
        reference = _reference_from_run(
            run,
            encoded_repo=encoded_repo,
            artifact_name=artifact_name,
            api_url=api_url,
            get_json=get_json,
        )
        if reference is not None:
            return reference
    return None


def _write_output(path: Path, reference: ArtifactReference | None) -> None:
    values: dict[str, str]
    if reference is None:
        values = {
            "found": "false",
            "run_id": "",
            "artifact_id": "",
        }
    else:
        values = {
            "found": "true",
            "run_id": str(reference.run_id),
            "artifact_id": str(reference.artifact_id),
        }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-age-hours", type=int, default=48)
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        parser.error("GITHUB_TOKEN is required")
    try:
        reference = resolve_artifact(
            repository=args.repository,
            workflow=args.workflow,
            branch=args.branch,
            artifact_name=args.artifact,
            api_url=args.api_url,
            get_json=_github_json_getter(token),
            max_age_hours=args.max_age_hours,
        )
    except ResolutionError as exc:
        print(f"NVD artifact resolution failed: {exc}", file=sys.stderr)
        return 1
    _write_output(args.output, reference)
    if reference is None:
        print("No fresh trusted NVD artifact was found; the audit must refresh or fail.")
    else:
        print(
            "Resolved trusted NVD artifact "
            f"{reference.artifact_id} from main run {reference.run_id}."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

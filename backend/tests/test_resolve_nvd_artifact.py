from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPOSITORY_ROOT / "backend" / "scripts" / "resolve_nvd_artifact.py"
REPOSITORY = "owner/repo"
WORKFLOW = "nvd-database.yml"
ARTIFACT = "ticketbox-nvd-database-compat1"
HEAD_SHA = "b" * 40
ARTIFACT_DIGEST = "sha256:" + "c" * 64
NOW = datetime(2026, 7, 24, 9, tzinfo=UTC)


def _load_script() -> object:
    spec = importlib.util.spec_from_file_location(
        "_test_resolve_nvd_artifact",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


resolver = _load_script()


def _run(
    run_id: int,
    *,
    event: str = "schedule",
    age: timedelta = timedelta(hours=1),
) -> dict[str, Any]:
    return {
        "id": run_id,
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": HEAD_SHA,
        "event": event,
        "path": ".github/workflows/nvd-database.yml",
        "repository": {"full_name": REPOSITORY},
        "created_at": (NOW - age).isoformat().replace("+00:00", "Z"),
    }


def _artifact(
    run_id: int,
    *,
    name: str = ARTIFACT,
    digest: str = ARTIFACT_DIGEST,
) -> dict[str, Any]:
    return {
        "id": run_id * 10,
        "name": name,
        "expired": False,
        "digest": digest,
        "workflow_run": {"id": run_id, "head_sha": HEAD_SHA},
    }


def _resolve(get_json: object) -> object:
    return resolver.resolve_artifact(
        repository=REPOSITORY,
        workflow=WORKFLOW,
        branch="main",
        artifact_name=ARTIFACT,
        api_url="https://api.github.test",
        get_json=get_json,
        now=NOW,
    )


def test_resolver_selects_newest_matching_artifact_from_trusted_main() -> None:
    observed: list[str] = []
    runs = [
        _run(1, event="pull_request"),
        _run(2, age=timedelta(hours=2)),
        _run(3, event="push", age=timedelta(minutes=30)),
    ]

    def get_json(url: str) -> dict[str, Any]:
        observed.append(url)
        if "/workflows/" in url:
            return {"workflow_runs": runs}
        assert "/runs/3/" in url
        return {"artifacts": [_artifact(3)]}

    assert _resolve(get_json) == resolver.ArtifactReference(run_id=3, artifact_id=30)
    assert not any("/runs/1/" in url or "/runs/2/" in url for url in observed)


def test_resolver_does_not_accept_another_database_compatibility_channel() -> None:
    runs = [_run(4)]

    def get_json(url: str) -> dict[str, Any]:
        if "/workflows/" in url:
            return {"workflow_runs": runs}
        return {
            "artifacts": [
                _artifact(
                    4,
                    name="ticketbox-nvd-database-compat2",
                )
            ]
        }

    assert _resolve(get_json) is None


def test_resolver_rejects_a_run_older_than_the_freshness_window() -> None:
    def get_json(url: str) -> dict[str, Any]:
        assert "/workflows/" in url
        return {"workflow_runs": [_run(5, age=timedelta(hours=49))]}

    assert _resolve(get_json) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "queued"),
        ("conclusion", "failure"),
        ("head_branch", "feature"),
        ("head_sha", "not-a-sha"),
        ("event", "pull_request"),
        ("path", ".github/workflows/other.yml"),
        ("repository", {"full_name": "fork/repo"}),
    ],
)
def test_resolver_rejects_untrusted_run_provenance(
    field: str,
    value: object,
) -> None:
    run = _run(5)
    run[field] = value

    def get_json(url: str) -> dict[str, Any]:
        assert "/workflows/" in url
        return {"workflow_runs": [run]}

    assert _resolve(get_json) is None


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("expired", True),
        ("digest", "sha256:not-a-digest"),
        ("head_sha", "d" * 40),
        ("run_id", 999),
    ],
)
def test_resolver_rejects_untrusted_artifact_metadata(
    mutation: str,
    value: object,
) -> None:
    run = _run(6)
    artifact = _artifact(6)
    if mutation == "run_id":
        artifact["workflow_run"]["id"] = value
    elif mutation == "head_sha":
        artifact["workflow_run"][mutation] = value
    else:
        artifact[mutation] = value

    def get_json(url: str) -> dict[str, Any]:
        if "/workflows/" in url:
            return {"workflow_runs": [run]}
        return {"artifacts": [artifact]}

    assert _resolve(get_json) is None


def test_missing_main_producer_is_reported_without_bootstrap_artifact() -> None:
    def missing(_url: str) -> dict[str, Any]:
        raise resolver.ResourceNotFoundError("not merged yet")

    result = resolver.resolve_artifact_state(
        repository=REPOSITORY,
        workflow=WORKFLOW,
        branch="main",
        artifact_name=ARTIFACT,
        api_url="https://api.github.test",
        get_json=missing,
        now=NOW,
    )

    assert result.producer_available is False
    assert result.reference is None

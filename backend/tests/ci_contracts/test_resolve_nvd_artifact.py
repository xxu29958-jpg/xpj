from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from tests._infra.ci_gap import load_ci_script

resolver = load_ci_script("resolve_nvd_artifact.py")

REPOSITORY = "owner/repo"
WORKFLOW = "nvd-database.yml"
ARTIFACT = "ticketbox-nvd-database-v12.2.0"
HEAD_SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
NOW = datetime(2026, 7, 24, 9, tzinfo=UTC)


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
    digest: str = DIGEST,
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


def test_resolver_selects_newest_immutable_artifact_from_trusted_main_run() -> None:
    observed: list[str] = []
    runs = [
        _run(1, event="pull_request"),
        _run(2, age=timedelta(hours=2)),
        _run(3, event="push", age=timedelta(minutes=30)),
    ]

    def get_json(url: str) -> dict[str, Any]:
        observed.append(url)
        if "/workflows/" in url:
            assert "branch=main" in url
            assert "status=success" in url
            return {"workflow_runs": runs}
        assert "/runs/3/" in url
        return {"artifacts": [_artifact(3)]}

    reference = _resolve(get_json)

    assert reference == resolver.ArtifactReference(
        run_id=3,
        artifact_id=30,
    )
    assert not any("/runs/1/" in url or "/runs/2/" in url for url in observed)


def test_resolver_skips_stale_runs_and_wrong_plugin_artifacts() -> None:
    runs = [
        _run(4, age=timedelta(hours=49)),
        _run(5, age=timedelta(hours=2)),
        _run(6, age=timedelta(hours=3)),
    ]

    def get_json(url: str) -> dict[str, Any]:
        if "/workflows/" in url:
            return {"workflow_runs": runs}
        if "/runs/5/" in url:
            return {"artifacts": [_artifact(5, name="ticketbox-nvd-database-v11")]}
        assert "/runs/6/" in url
        return {"artifacts": [_artifact(6)]}

    reference = _resolve(get_json)

    assert reference is not None
    assert reference.run_id == 6


def test_resolver_rejects_expired_ambiguous_or_malformed_artifacts() -> None:
    runs = [_run(7), _run(8), _run(9)]

    def get_json(url: str) -> dict[str, Any]:
        if "/workflows/" in url:
            return {"workflow_runs": runs}
        run_id = int(url.split("/runs/", 1)[1].split("/", 1)[0])
        artifact = _artifact(run_id)
        if run_id == 7:
            artifact["expired"] = True
            return {"artifacts": [artifact]}
        if run_id == 8:
            return {"artifacts": [artifact, dict(artifact)]}
        artifact["digest"] = "sha256:not-a-digest"
        return {"artifacts": [artifact]}

    assert _resolve(get_json) is None


def test_resolver_treats_unmerged_producer_workflow_as_bootstrap() -> None:
    def missing(_url: str) -> dict[str, Any]:
        raise resolver.ResourceNotFoundError("not merged yet")

    assert _resolve(missing) is None

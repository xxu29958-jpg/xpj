"""Stable task anchors for the engineering map. Not a CI skip authority."""

from __future__ import annotations

from pathlib import Path

if __package__:
    from .repository_weight_sources import git_path_exists
else:
    from repository_weight_sources import git_path_exists

ROOT = Path(__file__).resolve().parents[2]

_CI_CHAIN = (
    ("backend/scripts/ci_gap_trigger_scope.py", "classifier", "declared_anchor"),
    ("backend/scripts/ci_scope.py", "transport", "declared_anchor"),
    (".github/workflows/ci.yml", "workflow", "test_or_runtime_consumer"),
    (".github/workflows/android-connected-test.yml", "workflow", "test_or_runtime_consumer"),
    ("backend/scripts/verify_scoped_ci_results.py", "aggregator", "declared_anchor"),
    ("backend/tests/test_ci_scope.py", "classifier_tests", "test_or_runtime_consumer"),
    ("backend/tests/test_backend_ci_results.py", "aggregator_tests", "test_or_runtime_consumer"),
)

_SHARED_WEB = (
    ("backend/app/static/shared/tokens.css", "query_entry", "declared_responsibility"),
    ("desktop/backend_manager/web_bff.py", "bff_allowlist", "declared_anchor"),
    ("backend/tests/test_ci_scope.py", "scope_consumer", "test_or_runtime_consumer"),
    ("desktop/tests/test_web_bff.py", "desktop_allowlist_tests", "test_or_runtime_consumer"),
    ("desktop/tests/test_web_bff_edge_e2e.py", "desktop_runtime_consumer", "test_or_runtime_consumer"),
    ("backend/app/templates/web/base.html", "web_loader", "name_search_clue"),
)


def _node(repo: Path, source_sha: str, path: str, role: str, evidence: str) -> dict[str, object]:
    present = git_path_exists(repo, source_sha, path)
    return {
        "path": path,
        "role": role,
        "evidence": evidence if present else "unknown",
        "present": present,
    }


def resolve_task(
    name: str,
    repo: Path | None = None,
    source_sha: str | None = None,
    *,
    historical: bool = False,
) -> dict[str, object]:
    root = repo or ROOT
    if not source_sha:
        raise ValueError("task map requires an exact source SHA")
    if name == "ci-trigger":
        chain = _CI_CHAIN
        title = "Why this change selected these CI jobs"
        extra = {
            "notes": (
                "Rules live in ci_gap_trigger_scope.classify_ci_decision; "
                "ci_scope only transports the same decision."
            ),
        }
    elif name == "shared-web-theme":
        chain = _SHARED_WEB
        title = "Why a shared Web theme change also selects Desktop"
        extra = {
            "entry": "backend/app/static/shared/tokens.css",
            "notes": (
                "Desktop BFF allowed_target() allowlists /static/shared/; "
                "classifier prefix rules consume that allowlist."
            ),
        }
    else:
        raise ValueError(f"unknown task: {name}")
    return {
        "task": name,
        "title": title,
        "source_sha": source_sha,
        "historical": historical,
        "map_is_skip_authority": False,
        "chain": [_node(root, source_sha, path, role, evidence) for path, role, evidence in chain],
        **extra,
    }


def render_task(task: dict[str, object]) -> str:
    lines = [
        f"TASK {task['task']}: {task['title']}",
        f"source_sha={task['source_sha']} historical={str(task['historical']).lower()}",
        f"map_is_skip_authority={task['map_is_skip_authority']}",
        str(task.get("notes") or ""),
        "chain:",
    ]
    for node in task["chain"]:
        lines.append(
            f"  {node['evidence']} {node['role']} {node['path']} present={str(node['present']).lower()}"
        )
    return "\n".join(lines) + "\n"

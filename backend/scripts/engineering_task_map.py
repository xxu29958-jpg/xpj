"""Stable task anchors for the engineering map. Not a CI skip authority."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_CI_CHAIN = (
    ("backend/scripts/ci_gap_trigger_scope.py", "classifier", "static_reference"),
    ("backend/scripts/ci_scope.py", "transport", "static_reference"),
    (".github/workflows/ci.yml", "workflow", "test_or_runtime_consumer"),
    (".github/workflows/android-connected-test.yml", "workflow", "test_or_runtime_consumer"),
    ("backend/scripts/verify_scoped_ci_results.py", "aggregator", "static_reference"),
    ("backend/tests/test_ci_scope.py", "classifier_tests", "test_or_runtime_consumer"),
    ("backend/tests/test_backend_ci_results.py", "aggregator_tests", "test_or_runtime_consumer"),
)

_SHARED_WEB = (
    ("backend/app/static/shared/tokens.css", "query_entry", "declared_responsibility"),
    ("desktop/backend_manager/web_bff.py", "bff_allowlist", "static_reference"),
    ("backend/tests/test_ci_scope.py", "scope_consumer", "test_or_runtime_consumer"),
    ("desktop/tests/test_web_bff.py", "desktop_allowlist_tests", "test_or_runtime_consumer"),
    ("desktop/tests/test_web_bff_edge_e2e.py", "desktop_runtime_consumer", "test_or_runtime_consumer"),
    ("backend/app/templates/web/base.html", "web_loader", "name_search_clue"),
)


def _node(repo: Path, path: str, role: str, evidence: str) -> dict[str, object]:
    target = repo / path
    return {
        "path": path,
        "role": role,
        "evidence": evidence if target.is_file() else "unknown",
        "present": target.is_file(),
    }


def resolve_task(name: str, repo: Path | None = None) -> dict[str, object]:
    root = repo or ROOT
    if name == "ci-trigger":
        return {
            "task": name,
            "title": "Why this change selected these CI jobs",
            "map_is_skip_authority": False,
            "chain": [_node(root, path, role, evidence) for path, role, evidence in _CI_CHAIN],
            "notes": (
                "Rules live in ci_gap_trigger_scope.classify_ci_decision; "
                "ci_scope only transports the same decision."
            ),
        }
    if name == "shared-web-theme":
        return {
            "task": name,
            "title": "Why a shared Web theme change also selects Desktop",
            "map_is_skip_authority": False,
            "entry": "backend/app/static/shared/tokens.css",
            "chain": [_node(root, path, role, evidence) for path, role, evidence in _SHARED_WEB],
            "notes": (
                "Desktop BFF allowed_target() allowlists /static/shared/; "
                "classifier prefix rules consume that allowlist."
            ),
        }
    raise ValueError(f"unknown task: {name}")


def render_task(task: dict[str, object]) -> str:
    lines = [
        f"TASK {task['task']}: {task['title']}",
        f"map_is_skip_authority={task['map_is_skip_authority']}",
        str(task.get("notes") or ""),
        "chain:",
    ]
    for node in task["chain"]:
        lines.append(
            f"  {node['evidence']} {node['role']} {node['path']} present={str(node['present']).lower()}"
        )
    return "\n".join(lines) + "\n"

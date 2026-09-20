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

_QUALIFICATION_TASKS = {
    "ci-failure": {
        "title": "Read the original failure before following its qualification owner",
        "chain": (
            (".github/workflows/ci.yml", "execution", "test_or_runtime_consumer"),
            ("backend/scripts/check_api_contract.py", "api_snapshot_check", "declared_anchor"),
            ("backend/scripts/verify_backend_ci_results.py", "backend_qualification", "declared_anchor"),
            ("backend/scripts/verify_scoped_ci_results.py", "lane_qualification", "declared_anchor"),
            ("backend/scripts/ci_run_timing.py", "completed_run_timing", "declared_anchor"),
            ("backend/tests/test_backend_ci_results.py", "failure_propagation", "test_or_runtime_consumer"),
        ),
        "notes": "Keep run/attempt/job/step and the original rule/test error. An anchor is a lead, not a root-cause finding.",
        "reproduce": "API snapshot drift: python backend/scripts/check_api_contract.py; other failures: use the failed step's exact command.",
        "qualification": "CI Backend contracts -> Backend; complete affected PostgreSQL, Windows, Android and CodeQL obligations independently.",
    },
    "android-qualification": {
        "title": "Android build, device results and process qualification",
        "chain": (
            (".github/workflows/android-connected-test.yml", "device_execution", "test_or_runtime_consumer"),
            ("android/app/build.gradle.kts", "build_and_evidence_tasks", "declared_anchor"),
            ("android/scripts/verify_android_test_qualification.py", "result_and_process_qualification", "declared_anchor"),
            ("backend/tests/test_android_test_qualification.py", "result_counterexamples", "test_or_runtime_consumer"),
            ("backend/tests/test_android_process_qualification.py", "process_counterexamples", "test_or_runtime_consumer"),
        ),
        "notes": "Use the original Gradle task/test ID and XML or process error; device evidence must be captured while its isolated emulator is alive.",
        "reproduce": "From android/, with ANDROID_SERIAL bound to an isolated emulator: ./gradlew --no-daemon --max-workers=2 :app:connectedGrayDebugAndroidTest",
        "qualification": "Android fast + debug/release APK + SCA -> Android; Connected execution with live-device finalizer -> Connected (emulator); CodeQL extraction remains separate.",
    },
    "postgres-qualification": {
        "title": "PostgreSQL collection, isolated shards and recovery",
        "chain": (
            (".github/workflows/ci.yml", "database_execution", "test_or_runtime_consumer"),
            ("backend/scripts/run_postgres_pytest_lane.py", "selection_and_shards", "declared_anchor"),
            ("backend/scripts/test_postgres_contract.py", "cluster_contract", "declared_anchor"),
            ("backend/tests/conftest.py", "database_and_worker_isolation", "test_or_runtime_consumer"),
            ("backend/tests/test_postgres_ci_lane_runner.py", "collection_and_failure_contracts", "test_or_runtime_consumer"),
            ("backend/tests/test_postgres_ci_topology.py", "recovery_and_aggregation_wiring", "test_or_runtime_consumer"),
        ),
        "notes": "Read nodeid plus setup/call/teardown duration. Preserve ordinary/real-db/recovery boundaries; counts or map anchors do not prove a test passed.",
        "reproduce": "From backend/, with the authorized isolated PostgreSQL test environment: python -m scripts.run_postgres_pytest_lane --lane real-db --workers 1",
        "qualification": "All ordinary and real-db shards + real PostgreSQL smoke and backup/restore drill -> Backend (PostgreSQL).",
    },
}


def _node(repo: Path, snapshot_sha: str, path: str, role: str, evidence: str) -> dict[str, object]:
    present = git_path_exists(repo, snapshot_sha, path)
    return {
        "path": path,
        "role": role,
        "evidence": evidence if present else "unknown",
        "present": present,
    }


def resolve_task(
    name: str,
    repo: Path | None = None,
    snapshot_sha: str | None = None,
    *,
    historical: bool = False,
    source_sha: str | None = None,
) -> dict[str, object]:
    root = repo or ROOT
    if not snapshot_sha:
        raise ValueError("task map requires an exact snapshot SHA")
    display_source = source_sha or snapshot_sha
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
    elif name in _QUALIFICATION_TASKS:
        definition = _QUALIFICATION_TASKS[name]
        chain = definition["chain"]
        title = definition["title"]
        extra = {key: value for key, value in definition.items() if key not in {"chain", "title"}}
    else:
        raise ValueError(f"unknown task: {name}")
    return {
        "task": name,
        "title": title,
        "snapshot_sha": snapshot_sha,
        "measurement_sha": snapshot_sha,
        "source_sha": display_source,
        "historical": historical,
        "map_is_skip_authority": False,
        "chain": [_node(root, snapshot_sha, path, role, evidence) for path, role, evidence in chain],
        **extra,
    }


def render_task(task: dict[str, object]) -> str:
    lines = [
        f"TASK {task['task']}: {task['title']}",
        (
            f"source_sha={task['source_sha']} measurement_sha={task['measurement_sha']} "
            f"historical={str(task['historical']).lower()}"
        ),
        f"map_is_skip_authority={task['map_is_skip_authority']}",
        str(task.get("notes") or ""),
        "chain:",
    ]
    for node in task["chain"]:
        lines.append(
            f"  {node['evidence']} {node['role']} {node['path']} present={str(node['present']).lower()}"
        )
    for key in ("reproduce", "qualification"):
        if task.get(key):
            lines.append(f"{key}: {task[key]}")
    return "\n".join(lines) + "\n"

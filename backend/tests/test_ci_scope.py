from __future__ import annotations

import json

from scripts import ci_scope
from scripts.ci_gap_trigger_scope import all_ci_scopes, classify_ci_paths
from scripts.postgres_release_policy import POSTGRES_RELEASE_POLICY


def test_docs_only_change_skips_heavy_jobs() -> None:
    assert classify_ci_paths(["docs/runbook/CI.md", "README.md"]) == {
        "postgres": False,
        "backend_frozen": False,
        "desktop": False,
        "android": False,
        "windows": False,
    }


def test_android_source_change_runs_only_android_job() -> None:
    assert classify_ci_paths(["android/app/src/main/java/com/ticketbox/MainActivity.kt"]) == {
        "postgres": False,
        "backend_frozen": False,
        "desktop": False,
        "android": True,
        "windows": False,
    }


def _assert_path_scopes(paths: tuple[str, ...], *enabled: str) -> None:
    expected = dict.fromkeys(
        ("postgres", "backend_frozen", "desktop", "android", "windows"),
        False,
    )
    for scope in enabled:
        expected[scope] = True
    for path in paths:
        assert classify_ci_paths([path]) == expected


def test_backend_and_packaging_changes_compose_scopes() -> None:
    assert classify_ci_paths(
        ["backend/app/services/report_service.py", "backend/packaging/ticketbox.iss"]
    ) == {
        "postgres": True,
        "backend_frozen": True,
        "desktop": False,
        "android": False,
        "windows": True,
    }
    _assert_path_scopes(
        (
            "backend/requirements-build.txt",
            "backend/requirements-build.lock",
            "backend/scripts/start_test_pg.ps1",
            "backend/scripts/stop_test_pg.ps1",
            "backend/scripts/test_pg_auth_contract.ps1",
            "backend/scripts/test_pg_ownership_contract.ps1",
            "backend/scripts/test_pg_process_contract.ps1",
            "backend/scripts/test_pg_storage_contract.ps1",
            "backend/scripts/windows_build_provenance.ps1",
            "backend/scripts/windows_backend_build_provenance.ps1",
            "backend/tests/_infra/windows_tree.py",
            "backend/packaging/audit/test_count_baseline.txt",
        ),
        "windows",
    )
    _assert_path_scopes(
        ("backend/audit/test_count_baseline.txt",),
        "postgres",
    )
    _assert_path_scopes(("backend/app/main.py",), "postgres", "backend_frozen")
    _assert_path_scopes(
        (
            "backend/migrations/versions/20260720_0001_example.py",
        ),
        "postgres",
        "backend_frozen",
    )
    _assert_path_scopes(
        ("backend/requirements.txt",),
        "postgres",
        "backend_frozen",
        "windows",
    )
    _assert_path_scopes(
        (
            "backend/alembic.ini",
            "backend/requirements-dev.txt",
            "backend/scripts/test_postgres_contract.json",
        ),
        "postgres",
        "windows",
    )
    _assert_path_scopes(
        ("backend/packaging/windows-build-toolchain.json",),
        "postgres",
        "windows",
    )
    _assert_path_scopes(
        ("backend/packaging/windows-release-config.json",),
        "postgres",
        "desktop",
        "windows",
    )
    assert classify_ci_paths(
        ["backend/tests/test_new_feature.py", "backend/audit/test_count_baseline.txt"]
    ) == {
        "postgres": True,
        "backend_frozen": False,
        "desktop": False,
        "android": False,
        "windows": False,
    }


def test_desktop_build_contract_runs_tests_and_packaging() -> None:
    for path in (
        "desktop/backend_manager/__main__.py",
        "desktop/packaging/ticketbox-manager.spec",
        "desktop/scripts/build_manager_exe.ps1",
        "desktop/scripts/windows_manager_build_provenance.ps1",
        "desktop/pyproject.toml",
        "desktop/requirements-build.txt",
        "desktop/requirements-build.lock",
    ):
        assert classify_ci_paths([path]) == {
            "postgres": False,
            "backend_frozen": False,
            "desktop": True,
            "android": False,
            "windows": True,
        }


def test_version_contract_crosses_backend_desktop_and_packaging() -> None:
    assert classify_ci_paths(["backend/app/version.py"]) == {
        "postgres": True,
        "backend_frozen": False,
        "desktop": True,
        "android": False,
        "windows": True,
    }


def test_always_on_contract_tests_do_not_expand_heavy_scopes() -> None:
    for path in (
        "backend/tests/test_android_connected_process_health.py",
        "backend/tests/test_backend_ci_results.py",
        "backend/tests/test_postgres_ci_topology.py",
    ):
        assert classify_ci_paths([path]) == {
            "postgres": False,
            "backend_frozen": False,
            "desktop": False,
            "android": False,
            "windows": False,
        }


def test_ci_policy_and_unknown_paths_fail_closed_to_full() -> None:
    assert classify_ci_paths([".github/workflows/ci.yml"]) == all_ci_scopes()
    assert classify_ci_paths(["backend/scripts/ci_gap_workflow_parser.py"]) == all_ci_scopes()
    for path in (
        "backend/scripts/_audit_codebase.py",
        "backend/scripts/codebase_audit_gate.py",
        "backend/scripts/pr_delta_baselines.py",
        "backend/scripts/postgres_release_policy.py",
        "backend/scripts/release_audit.py",
        "backend/scripts/report_qualification_sha.py",
        "backend/scripts/verify_backend_ci_results.py",
    ):
        assert classify_ci_paths([path]) == all_ci_scopes()
    assert classify_ci_paths(["new-surface/config.toml"]) == all_ci_scopes()
    assert classify_ci_paths(["backend/new_runtime_surface.py"]) == all_ci_scopes()
    assert classify_ci_paths([" docs/runbook/CI.md"]) == all_ci_scopes()
    assert classify_ci_paths(["docs/runbook/CI.md "]) == all_ci_scopes()
    assert classify_ci_paths(["   "]) == all_ci_scopes()
    assert classify_ci_paths([]) == all_ci_scopes()


def test_scope_output_derives_postgres_matrix_from_release_policy(tmp_path) -> None:
    output = tmp_path / "github-output"

    ci_scope.write_outputs(output, all_ci_scopes())

    values = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert json.loads(values["postgres_matrix"]) == json.loads(
        POSTGRES_RELEASE_POLICY.matrix_json()
    )


def test_changed_paths_is_rename_and_newline_safe(monkeypatch) -> None:
    observed: list[str] = []

    def fake_run(command, **kwargs):
        observed.extend(command)
        assert kwargs == {"check": True, "capture_output": True}
        return type("Completed", (), {"stdout": b"old name.py\0new\nname.py\0"})()

    monkeypatch.setattr(ci_scope.subprocess, "run", fake_run)

    assert ci_scope.changed_paths("base", "head") == ["old name.py", "new\nname.py"]
    assert observed == [
        "git",
        "diff",
        "--no-renames",
        "--name-only",
        "-z",
        "base...head",
    ]

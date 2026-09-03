from __future__ import annotations

import json
from pathlib import Path

from scripts import ci_gap_trigger_scope, ci_scope
from scripts.ci_gap_trigger_scope import all_ci_scopes, classify_ci_paths
from scripts.postgres_release_policy import POSTGRES_RELEASE_POLICY

BACKEND_ROOT = Path(__file__).resolve().parents[1]


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
    assert classify_ci_paths(["backend/app/services/report_service.py", "backend/packaging/ticketbox.iss"]) == {
        "postgres": True,
        "backend_frozen": True,
        "desktop": False,
        "android": False,
        "windows": True,
    }


def test_windows_build_inputs_select_windows_scope() -> None:
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
            "backend/scripts/windows_python_build_environment.ps1",
            "backend/tests/_infra/windows_tree.py",
            "backend/packaging/audit/test_count_baseline.txt",
        ),
        "windows",
    )


def test_backend_runtime_inputs_select_execution_scopes() -> None:
    _assert_path_scopes(
        ("backend/audit/test_count_baseline.txt",),
        "postgres",
    )
    _assert_path_scopes(
        ("backend/app/main.py",),
        "postgres",
        "backend_frozen",
        "windows",
    )
    _assert_path_scopes(
        (
            "backend/app/services/runtime_settings_store.py",
            "backend/app/services/secure_file.py",
            "backend/app/services/secure_file_windows.py",
            "backend/app/services/secure_file_windows_acl.py",
        ),
        "postgres",
        "backend_frozen",
        "windows",
    )
    _assert_path_scopes(
        ("backend/migrations/versions/20260720_0001_example.py",),
        "postgres",
        "backend_frozen",
    )
    _assert_path_scopes(
        ("backend/requirements.txt",),
        "postgres",
        "backend_frozen",
        "windows",
    )


def test_backend_tooling_and_packaging_inputs_select_execution_scopes() -> None:
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
        ("distribution/windows/installer/ticketbox.iss", "distribution/windows/tests/test_cli.py"),
        "windows",
    )
    _assert_path_scopes(
        ("backend/packaging/windows-release-config.json",),
        "postgres",
        "desktop",
        "windows",
    )
    assert classify_ci_paths(["backend/tests/test_new_feature.py", "backend/audit/test_count_baseline.txt"]) == {
        "postgres": True,
        "backend_frozen": False,
        "desktop": False,
        "android": False,
        "windows": False,
    }


def test_dataset_maintenance_changes_select_all_required_execution_scopes() -> None:
    _assert_path_scopes(
        (
            "backend/app/database_maintenance_runtime.py",
            "backend/app/dataset_maintenance_cli.py",
            "backend/app/database/_dataset_backup_action.py",
            "backend/app/database/_dataset_backup_snapshot.py",
            "backend/app/database/_dataset_restore_action.py",
            "backend/app/database/_dataset_restore_authority.py",
            "backend/app/database/_dataset_restore_security.py",
        ),
        "postgres",
        "backend_frozen",
        "windows",
    )


def test_dataset_maintenance_transitive_app_dependencies_select_windows() -> None:
    dependencies = ci_gap_trigger_scope.dataset_maintenance_python_dependencies()
    assert "backend/app/__init__.py" in dependencies
    assert "backend/app/database_maintenance_runtime.py" in dependencies
    assert "backend/app/dataset_maintenance_cli.py" in dependencies
    assert "backend/app/models/__init__.py" in dependencies
    for dependency in dependencies:
        assert classify_ci_paths([dependency])["windows"], dependency


def test_fresh_install_helper_transitive_dependencies_select_windows() -> None:
    dependencies = ci_gap_trigger_scope.fresh_install_python_dependencies()
    assert "backend/app/database/_fresh_schema_upgrade.py" in dependencies
    assert "backend/app/services/identity_service/__init__.py" in dependencies
    assert "backend/app/services/identity_service/_bootstrap.py" in dependencies
    for dependency in dependencies:
        scopes = classify_ci_paths([dependency])
        assert scopes["postgres"], dependency
        assert scopes["backend_frozen"], dependency
        assert scopes["windows"], dependency


def test_installation_health_transitive_dependencies_select_windows() -> None:
    dependencies = ci_gap_trigger_scope.installation_health_python_dependencies()
    assert "backend/app/database/_database_generation_runtime_admission.py" in dependencies
    assert "backend/app/database/_database_generation_runtime_queries.py" in dependencies
    assert "backend/app/services/installation_health_attestation.py" in dependencies
    assert "backend/app/services/installation_health_service.py" in dependencies
    for dependency in dependencies:
        scopes = classify_ci_paths([dependency])
        assert scopes["postgres"], dependency
        assert scopes["backend_frozen"], dependency
        assert scopes["windows"], dependency


def test_shared_web_surface_selects_desktop_edge_consumer() -> None:
    for path in (
        "backend/app/static/web/appearance-bootstrap.js",
        "backend/app/static/web/desktop/theme.js",
        "backend/app/static/web/desktop.js",
        "backend/app/templates/web/base.html",
    ):
        _assert_path_scopes((path,), "postgres", "backend_frozen", "desktop")
    ordinary = classify_ci_paths(["backend/app/services/report_service.py"])
    assert ordinary["postgres"] is True
    assert ordinary["backend_frozen"] is True
    assert ordinary["desktop"] is False


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
        "backend/tests/test_android_test_qualification.py",
        "backend/tests/test_backend_ci_results.py",
        "backend/tests/test_postgres_ci_lane_runner.py",
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
        "backend/scripts/verify_codeql_required_context.py",
    ):
        assert classify_ci_paths([path]) == all_ci_scopes()
    assert classify_ci_paths(["new-surface/config.toml"]) == all_ci_scopes()
    assert classify_ci_paths(["backend/new_runtime_surface.py"]) == all_ci_scopes()
    assert classify_ci_paths([" docs/runbook/CI.md"]) == all_ci_scopes()
    assert classify_ci_paths(["docs/runbook/CI.md "]) == all_ci_scopes()
    assert classify_ci_paths(["   "]) == all_ci_scopes()
    assert classify_ci_paths([]) == all_ci_scopes()


def test_required_codeql_context_needs_every_analysis_lane() -> None:
    from scripts.verify_codeql_required_context import verify

    ok, message = verify(
        {
            "EXPECTED_SHA": "abc",
            "SCRIPTED_RESULT": "success",
            "ANDROID_RESULT": "success",
        }
    )
    assert ok is True
    assert "abc" in message
    ok, message = verify({"SCRIPTED_RESULT": "success", "ANDROID_RESULT": "success"})
    assert ok is False
    assert "EXPECTED_SHA" in message
    ok, message = verify(
        {
            "EXPECTED_SHA": "abc",
            "SCRIPTED_RESULT": "failure",
            "ANDROID_RESULT": "success",
        }
    )
    assert ok is False
    assert "scripted" in message
    ok, message = verify(
        {
            "EXPECTED_SHA": "abc",
            "SCRIPTED_RESULT": "success",
            "ANDROID_RESULT": "skipped",
        }
    )
    assert ok is False
    assert "Android" in message


def test_scope_output_derives_postgres_matrix_from_release_policy(tmp_path) -> None:
    output = tmp_path / "github-output"

    ci_scope.write_outputs(output, all_ci_scopes())

    values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert json.loads(values["postgres_matrix"]) == json.loads(POSTGRES_RELEASE_POLICY.matrix_json())


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

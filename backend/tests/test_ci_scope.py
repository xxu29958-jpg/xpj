from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import ci_gap_trigger_scope, ci_scope
from scripts.ci_gap_trigger_scope import all_ci_scopes, classify_ci_decision, classify_ci_paths
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


def test_android_source_and_openapi_snapshot_run_only_android_job() -> None:
    # OpenApiContractGateTest reads this snapshot to drive actual Moshi DTO checks.
    _assert_path_scopes(
        (
            "android/app/src/main/java/com/ticketbox/MainActivity.kt",
            "docs/architecture/openapi_contract.json",
        ),
        "android",
    )


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
        "backend/app/static/web/pwa-register.js",
        "backend/app/static/web/sw.js",
        "backend/app/static/web/product/shell.css",
        "backend/app/static/web/product/components.css",
        "backend/app/static/web/product/domains/inbox.css",
        "backend/app/static/web/fonts/NotoSansSC-Regular.woff2",
        "backend/app/static/web/product/brand/brand-mark.png",
        "backend/app/static/web/product/textures/paper-fiber.webp",
        "backend/app/static/shared/tokens.css",
        "backend/app/static/shared/csrf.js",
        "backend/app/static/shared/confirm-modal.js",
        "backend/app/static/shared/confirm-modal.css",
        "backend/app/templates/web/base.html",
        "backend/app/templates/web/pending.html",
        "backend/app/templates/web/_sidebar_nav.html",
        "backend/app/templates/web/_inbox_capture.html",
        "backend/app/routes/web_app.py",
        "backend/app/routes/web_pending.py",
        "backend/app/routes/web_common.py",
        "backend/app/routes/_web_session_common.py",
        "backend/app/routes/_web_pending_enrichment_watch.py",
        "backend/app/routes/_web_money_views.py",
    ):
        _assert_path_scopes((path,), "postgres", "backend_frozen", "desktop", "windows")
    _assert_path_scopes(
        ("backend/app/routes/web_auth.py",),
        "postgres",
        "backend_frozen",
    )
    _assert_path_scopes(
        ("backend/app/static/owner/app.css",),
        "postgres",
        "backend_frozen",
    )
    ordinary = classify_ci_paths(["backend/app/services/report_service.py"])
    assert ordinary["postgres"] is True
    assert ordinary["backend_frozen"] is True
    assert ordinary["desktop"] is False
    assert ordinary["windows"] is False


def test_desktop_bff_static_prefixes_follow_allowlist() -> None:
    prefixes = ci_gap_trigger_scope.desktop_bff_static_repo_prefixes()
    assert prefixes
    assert "backend/app/static/web/" in prefixes
    assert "backend/app/static/shared/" in prefixes
    assert "backend/app/static/owner/" not in prefixes
    for prefix in prefixes:
        _assert_path_scopes((f"{prefix}probe.css",), "postgres", "backend_frozen", "desktop", "windows")


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


def test_real_desktop_backend_consumers_require_the_native_postgres_lane() -> None:
    for path in (
        "desktop/tests/_edge_cdp.py",
        "desktop/tests/_real_backend.py",
        "desktop/tests/_real_backend_helper.py",
        "desktop/tests/test_web_bff_edge_e2e.py",
        "desktop/tests/test_desktop_first_use_backend.py",
        "desktop/tests/test_ui_browser_layout.py",
    ):
        _assert_path_scopes((path,), "desktop", "windows")


def test_web_edge_runtime_consumer_and_fixtures_select_windows_desktop_job() -> None:
    _assert_path_scopes(
        (
            "backend/tests/test_web_edge_runtime_contract.py",
            "backend/tests/fixtures/bulk_bar_announcement_contract.html",
            "backend/tests/fixtures/bulk_bar_empty_reload_contract.html",
            "backend/tests/fixtures/drawer_bulk_occ_contract.html",
            "backend/tests/fixtures/review_keyboard_contract.html",
            "backend/tests/fixtures/shell_keyboard_contract.html",
        ),
        "postgres",
        "desktop",
    )


def test_desktop_pairing_producers_require_the_real_desktop_consumer() -> None:
    for path in (
        "backend/app/auth.py",
        "backend/app/database/__init__.py",
        "backend/app/network_boundary.py",
        "backend/app/middleware/web_session.py",
        "backend/app/services/server_identity_service.py",
        "backend/app/services/session_refresh_service.py",
        "backend/app/services/ledger_contracts.py",
        "backend/app/services/ledger_archive_service.py",
        "backend/app/services/admin_service/_dtos.py",
        "backend/app/routes/auth.py",
        "backend/app/routes/devices.py",
        "backend/app/routes/ledgers.py",
        "backend/app/routes/desktop.py",
        "backend/app/services/owner_device_service.py",
        "backend/app/services/desktop_switch_service.py",
        "backend/app/services/ledger_service.py",
        "backend/app/schemas/_identity.py",
        "backend/app/services/desktop_activation_service.py",
        "backend/app/services/session_lifecycle_service.py",
        "backend/app/services/identity_service/__init__.py",
        "backend/app/services/identity_service/_pair.py",
        "backend/app/services/identity_service/_enrollment.py",
    ):
        _assert_path_scopes((path,), "postgres", "backend_frozen", "windows")


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

    ci_scope.write_outputs(output, all_ci_scopes(), {"android_apk": True, "android_connected": True})

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


def test_classifier_explanation_matches_existing_selection() -> None:
    docs = classify_ci_decision(["docs/runbook/CI.md"])
    assert docs["scopes"] == classify_ci_paths(["docs/runbook/CI.md"])
    assert docs["status"] == "NOT_AFFECTED"
    assert docs["lanes"]["android"]["status"] == "NOT_AFFECTED"
    shared = classify_ci_decision(["backend/app/static/shared/tokens.css"])
    assert shared["scopes"] == classify_ci_paths(["backend/app/static/shared/tokens.css"])
    assert shared["status"] == "REQUIRED"
    assert shared["lanes"]["desktop"]["status"] == "REQUIRED"
    assert shared["hits"][0]["consumer"] == "desktop_bff_static_allowlist"
    unknown = classify_ci_decision(["new-surface/config.toml"])
    assert unknown["scopes"] == all_ci_scopes()
    assert unknown["status"] == "UNKNOWN_FULL"
    empty = classify_ci_decision([])
    assert empty["status"] == "UNKNOWN_FULL"
    assert empty["reason"] == "empty path set"


def test_scope_cli_keeps_github_output_boolean_and_encodes_newline_paths(tmp_path, monkeypatch) -> None:
    output = tmp_path / "github-output"
    summary = tmp_path / "summary.md"
    monkeypatch.setattr(
        ci_scope,
        "changed_paths",
        lambda base, head: ["backend/app/static/shared/tokens.css", "weird\nname.css"],
    )
    monkeypatch.setattr(ci_scope.sys, "argv", [
        "ci_scope.py",
        "--event", "pull_request",
        "--base", "aa",
        "--head", "bb",
        "--output", str(output),
        "--summary", str(summary),
        "--explain-json", str(tmp_path / "explain.json"),
    ])
    assert ci_scope.main() == 0
    text = output.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("postgres=")
    assert "weird" not in text
    assert "android=true" in text
    rendered = summary.read_text(encoding="utf-8")
    assert r"weird\nname.css" in rendered
    assert "decision=UNKNOWN_FULL" in rendered
    explanation = json.loads((tmp_path / "explain.json").read_text(encoding="utf-8"))
    assert explanation["status"] == "UNKNOWN_FULL"
    assert explanation["scopes"] == all_ci_scopes()
    hit_paths = {hit["path"] for hit in explanation["hits"]}
    assert "backend/app/static/shared/tokens.css" in hit_paths
    assert "weird\nname.css" in hit_paths


def test_diff_unavailable_is_check_failed_full_not_unknown_full(monkeypatch) -> None:
    def boom(base, head):
        raise subprocess.CalledProcessError(1, ["git", "diff"])

    monkeypatch.setattr(ci_scope, "changed_paths", boom)
    decision = ci_scope.resolve_ci_scope("pull_request", "aa", "bb")
    assert decision["status"] == "CHECK_FAILED_FULL"
    assert decision["scopes"] == all_ci_scopes()
    assert decision["diff_error"] == "CalledProcessError"
    assert all(lane["status"] == "CHECK_FAILED" for lane in decision["lanes"].values())
    assert all(lane["status"] != "UNKNOWN_FULL" for lane in decision["lanes"].values())


def test_push_without_base_explains_unknown_full(tmp_path, monkeypatch) -> None:
    output = tmp_path / "github-output"
    summary = tmp_path / "summary.md"
    monkeypatch.setattr(ci_scope.sys, "argv", [
        "ci_scope.py", "--event", "push", "--output", str(output), "--summary", str(summary),
    ])
    assert ci_scope.main() == 0
    text = output.read_text(encoding="utf-8")
    assert all(f"{name}=true" in text for name in ("postgres", "backend_frozen", "desktop", "android", "windows"))
    assert "no trusted incremental diff base" in summary.read_text(encoding="utf-8")
    assert "decision=UNKNOWN_FULL" in summary.read_text(encoding="utf-8")


def test_scope_cli_reports_check_failed_full(tmp_path, monkeypatch) -> None:
    output = tmp_path / "github-output"
    summary = tmp_path / "summary.md"

    def boom(base, head):
        raise subprocess.CalledProcessError(1, ["git", "diff"])

    monkeypatch.setattr(ci_scope, "changed_paths", boom)
    monkeypatch.setattr(ci_scope.sys, "argv", [
        "ci_scope.py", "--event", "pull_request", "--base", "aa", "--head", "bb",
        "--output", str(output), "--summary", str(summary),
    ])
    assert ci_scope.main() == 0
    text = summary.read_text(encoding="utf-8")
    assert "decision=CHECK_FAILED_FULL" in text
    assert "CHECK_FAILED" in text
    assert "UNKNOWN_FULL" not in text


def test_mixed_policy_known_and_unknown_paths_keep_all_hit_explanations() -> None:
    decision = classify_ci_decision([
        ".github/workflows/ci.yml",
        "backend/app/static/shared/tokens.css",
        "new-surface/config.toml",
        "docs/runbook/CI.md",
    ])
    assert decision["status"] == "UNKNOWN_FULL"
    assert decision["scopes"] == all_ci_scopes()
    kinds = {hit["path"]: hit["kind"] for hit in decision["hits"]}
    assert kinds[".github/workflows/ci.yml"] == "workflow_prefix"
    assert kinds["backend/app/static/shared/tokens.css"] == "prefix"
    assert kinds["new-surface/config.toml"] == "unknown"
    assert kinds["docs/runbook/CI.md"] == "prefix"
    assert {hit["path"] for hit in decision["hits"]} == set(kinds)


@pytest.mark.parametrize("root,connected", [("test", False), ("androidTest", True)])
def test_android_pure_test_sources_keep_only_proven_capabilities(root, connected, tmp_path) -> None:
    paths = [f"android/app/src/{root}/java/com/ticketbox/ExampleTest.kt",
             f"android/app/src/{root}/kotlin/com/ticketbox/Fixture.kt"]
    decision = classify_ci_decision(paths)
    assert decision["scopes"] == {name: name == "android" for name in all_ci_scopes()}
    assert decision["android_capabilities"] == {"android_apk": False, "android_connected": connected}
    output = tmp_path / "outputs"
    ci_scope.write_outputs(output, decision["scopes"], decision["android_capabilities"])
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["android"] == "true"  # Fast, schema/count/static and security stay required.
    assert values["android_apk"] == "false"
    assert values["android_connected"] == str(connected).lower()
    assert "android_apk=false" in ci_scope.render_scope_explanation(decision)


@pytest.mark.parametrize("other", [
    "android/app/src/androidTest/java/com/ticketbox/DeviceTest.kt",
    "android/app/src/main/java/com/ticketbox/Example.kt",
    "android/app/src/test/AndroidManifest.xml",
    "android/app/src/test/java/build.gradle.kts",
    "android/app/src/test/resources/unknown.bin",
    "android/app/src/testFixtures/java/Fixture.kt",
    "android/app/schemas/com.ticketbox.Database/1.json",
    "android/audit/test_count_baseline.txt",
    "android/gradle/libs.versions.toml",
    "android/app/build.gradle.kts",
    "backend/app/main.py",
    "backend/tests/test_android_test_qualification.py",
    "backend/scripts/verify_scoped_ci_results.py",
    ".github/workflows/ci.yml",
    "docs/runbook/CI.md",
    "unknown/path.kt",
])
def test_android_mixed_or_unproven_inputs_keep_all_capabilities(other) -> None:
    decision = classify_ci_decision(["android/app/src/test/java/ExampleTest.kt", other])
    assert decision["android_capabilities"] == {"android_apk": True, "android_connected": True}


def test_android_renames_union_old_and_new_paths_and_do_not_infer_from_test_names() -> None:
    assert classify_ci_decision([
        "android/app/src/main/java/ExampleTest.kt", "android/app/src/test/java/ExampleTest.kt",
    ])["android_capabilities"]["android_apk"]
    assert classify_ci_decision([r"android\app\src\test\java\ExampleTest.kt"])["android_capabilities"] == {
        "android_apk": False, "android_connected": False,
    }
    assert classify_ci_decision(["android/app/src/test/java/../AndroidManifest.xml"])["android_capabilities"]["android_apk"]
    assert classify_ci_decision(["docs/README.md"])["android_capabilities"] == {
        "android_apk": False, "android_connected": False,
    }


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "repository_dispatch", "schedule", "unknown"])
def test_non_pr_qualification_always_requires_full_capabilities(event, monkeypatch) -> None:
    monkeypatch.setattr(ci_scope, "changed_paths", lambda *args: ["android/app/src/test/java/Test.kt"])
    decision = ci_scope.resolve_ci_scope(event, "base", "head")
    assert decision["scopes"] == all_ci_scopes()
    assert all(decision["android_capabilities"].values())

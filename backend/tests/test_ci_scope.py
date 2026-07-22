from __future__ import annotations

from scripts import ci_scope
from scripts.ci_gap_trigger_scope import all_ci_scopes, classify_ci_paths


def test_docs_only_change_skips_heavy_jobs() -> None:
    assert classify_ci_paths(["docs/runbook/CI.md", "README.md"]) == {
        "postgres": False,
        "desktop": False,
        "android": False,
        "windows": False,
    }


def test_android_source_change_runs_only_android_job() -> None:
    assert classify_ci_paths(["android/app/src/main/java/com/ticketbox/MainActivity.kt"]) == {
        "postgres": False,
        "desktop": False,
        "android": True,
        "windows": False,
    }


def test_backend_and_packaging_changes_compose_scopes() -> None:
    assert classify_ci_paths(
        ["backend/app/services/report_service.py", "backend/packaging/ticketbox.iss"]
    ) == {
        "postgres": True,
        "desktop": False,
        "android": False,
        "windows": True,
    }
    for path in (
        "backend/requirements-build.txt",
        "backend/requirements-build.lock",
        "backend/scripts/windows_build_provenance.ps1",
        "backend/scripts/windows_backend_build_provenance.ps1",
    ):
        assert classify_ci_paths([path]) == {
            "postgres": False,
            "desktop": False,
            "android": False,
            "windows": True,
        }

    for path in (
        "backend/app/main.py",
        "backend/migrations/versions/20260720_0001_example.py",
        "backend/alembic.ini",
        "backend/requirements.txt",
    ):
        assert classify_ci_paths([path]) == {
            "postgres": True,
            "desktop": False,
            "android": False,
            "windows": True,
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
            "desktop": True,
            "android": False,
            "windows": True,
        }


def test_version_contract_crosses_backend_desktop_and_packaging() -> None:
    assert classify_ci_paths(["backend/app/version.py"]) == {
        "postgres": True,
        "desktop": True,
        "android": False,
        "windows": True,
    }


def test_ci_policy_and_unknown_paths_fail_closed_to_full() -> None:
    assert classify_ci_paths([".github/workflows/ci.yml"]) == all_ci_scopes()
    assert classify_ci_paths(["backend/scripts/ci_gap_workflow_parser.py"]) == all_ci_scopes()
    assert classify_ci_paths(["new-surface/config.toml"]) == all_ci_scopes()
    assert classify_ci_paths([" docs/runbook/CI.md"]) == all_ci_scopes()
    assert classify_ci_paths(["docs/runbook/CI.md "]) == all_ci_scopes()
    assert classify_ci_paths(["   "]) == all_ci_scopes()
    assert classify_ci_paths([]) == all_ci_scopes()


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

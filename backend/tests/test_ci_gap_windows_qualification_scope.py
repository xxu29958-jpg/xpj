from pathlib import Path

import pytest

from tests._infra.ci_gap import load_ci_gap_module

pytestmark = pytest.mark.parallel_safe


def _write_scope(workflow: Path, *, close_artifacts_into_installer: bool) -> None:
    closure = (
        "            if ($scope.backend_exe_required -or "
        "$scope.manager_exe_required) {\n"
        "              $scope.installer_required = $true\n"
        "            }\n"
        if close_artifacts_into_installer
        else ""
    )
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n"
        "  backend:\n"
        "    steps:\n"
        "      - run: |\n"
        "          if ($true) {\n"
        "            foreach ($path in $changed) {\n"
        "              elseif ($path -match "
        "'^backend/scripts/windows_(build|backend_build)_provenance\\.ps1$') {\n"
        "                $scope.backend_exe_required = $true\n"
        "                $scope.manager_exe_required = $true\n"
        "              }\n"
        "              elseif ($path -eq "
        "'desktop/scripts/windows_manager_build_provenance.ps1') {\n"
        "                $scope.manager_exe_required = $true\n"
        "              }\n"
        "              elseif ($path -match '^backend/migrations/' -or "
        "$path -eq 'backend/alembic.ini') {\n"
        "                $scope.backend_exe_required = $true\n"
        "              }\n"
        "            }\n"
        f"{closure}"
        "          }\n",
        encoding="utf-8",
    )


def test_component_smoke_does_not_force_github_pr_installer_scope(
    tmp_path: Path,
) -> None:
    mod = load_ci_gap_module("ci_gap_windows_qualification")
    workflows = tmp_path / ".github" / "workflows"
    _write_scope(
        workflows / "ci.yml",
        close_artifacts_into_installer=False,
    )

    assert mod.github_pr_installer_dependency_scope_violations([workflows]) == []


def test_component_scope_rejects_implicit_installer_promotion(
    tmp_path: Path,
) -> None:
    mod = load_ci_gap_module("ci_gap_windows_qualification")
    workflows = tmp_path / ".github" / "workflows"
    _write_scope(
        workflows / "ci.yml",
        close_artifacts_into_installer=True,
    )

    assert mod.github_pr_installer_dependency_scope_violations([workflows]) == [
        "GitHub PR component smoke must not promote every frozen "
        "backend/Manager artifact into installer qualification",
    ]

from __future__ import annotations

from pathlib import Path

from test_ci_gap_release_scope import _GITEA_POLICY, _load, _write_valid_github


def test_ci_gap_release_apk_scope_policy_rejects_active_gitea_string_forgery(
    tmp_path: Path,
) -> None:
    mod = _load()
    github = _write_valid_github(tmp_path)
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    ci = workflows / "windows-ci.yml"
    ci.write_text(
        """
name: Windows CI
jobs:
  android:
    steps:
      - name: Detect release APK scope
        id: release-apk-scope
        run: |
          Write-Host 'function Set-ReleaseApkRequired'
          Write-Host '[System.IO.File]::AppendAllText $env:GITHUB_OUTPUT release_apk_required=$value'
          Write-Host '[System.Text.UTF8Encoding]::new($false)'
          Write-Host 'Set-ReleaseApkRequired "true" Set-ReleaseApkRequired "false"'
          Write-Host 'github.event_name github.ref_name workflow_dispatch refName -eq "main"'
          Write-Host 'git diff --name-only origin/main...HEAD git diff --name-only origin/main HEAD'
          Write-Host '$LASTEXITCODE Where-Object android/ .github/workflows/ .gitea/workflows/'
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: .\\gradlew.bat --no-daemon :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({github, ci}) == [_GITEA_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_disconnected_gitea_output_writes(
    tmp_path: Path,
) -> None:
    mod = _load()
    github = _write_valid_github(tmp_path)
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    ci = workflows / "windows-ci.yml"
    ci.write_text(
        """
name: Windows CI
jobs:
  android:
    steps:
      - name: Detect release APK scope
        id: release-apk-scope
        run: |
          function Set-ReleaseApkRequired([string]$value) {
            [System.IO.File]::AppendAllText(
              $env:GITHUB_OUTPUT,
              "release_apk_required=$value`n",
              [System.Text.UTF8Encoding]::new($false)
            )
          }
          Set-ReleaseApkRequired "true"
          Set-ReleaseApkRequired "false"
          $eventName = "${{ github.event_name }}"
          $refName = "${{ github.ref_name }}"
          if ($eventName -eq "workflow_dispatch" -or $refName -eq "main") {
            Write-Host "main/manual"
            exit 0
          }
          $changed = @(git diff --name-only origin/main...HEAD)
          if ($LASTEXITCODE -ne 0) {
            $changed = @(git diff --name-only origin/main HEAD)
          }
          if ($LASTEXITCODE -ne 0) {
            throw "Unable to compute changed files against origin/main"
          }
          $releaseRelevant = $changed | Where-Object {
            $_ -match '^(android/|\\.github/workflows/|\\.gitea/workflows/)'
          } | Select-Object -First 1
          if ($releaseRelevant) {
            Write-Host "release relevant"
          } else {
            Write-Host "backend-only"
          }
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: .\\gradlew.bat --no-daemon :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({github, ci}) == [_GITEA_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_gitea_main_block_hop(
    tmp_path: Path,
) -> None:
    mod = _load()
    github = _write_valid_github(tmp_path)
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    ci = workflows / "windows-ci.yml"
    ci.write_text(
        """
name: Windows CI
jobs:
  android:
    steps:
      - name: Detect release APK scope
        id: release-apk-scope
        run: |
          function Set-ReleaseApkRequired([string]$value) {
            [System.IO.File]::AppendAllText(
              $env:GITHUB_OUTPUT,
              "release_apk_required=$value`n",
              [System.Text.UTF8Encoding]::new($false)
            )
          }
          $eventName = "${{ github.event_name }}"
          $refName = "${{ github.ref_name }}"
          if ($eventName -eq "workflow_dispatch" -or $refName -eq "main") {
            Write-Host "forgot output"
          }
          if ($true) {
            Set-ReleaseApkRequired "true"
            exit 0
          }
          $changed = @(git diff --name-only origin/main...HEAD)
          if ($LASTEXITCODE -ne 0) {
            $changed = @(git diff --name-only origin/main HEAD)
          }
          if ($LASTEXITCODE -ne 0) {
            throw "Unable to compute changed files against origin/main"
          }
          $releaseRelevant = $changed | Where-Object {
            $_ -match '^(android/|\\.github/workflows/|\\.gitea/workflows/)'
          } | Select-Object -First 1
          if ($releaseRelevant) {
            Set-ReleaseApkRequired "true"
          } else {
            Set-ReleaseApkRequired "false"
          }
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: .\\gradlew.bat --no-daemon :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({github, ci}) == [_GITEA_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_gitea_path_block_hop(
    tmp_path: Path,
) -> None:
    mod = _load()
    github = _write_valid_github(tmp_path)
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True)
    ci = workflows / "windows-ci.yml"
    ci.write_text(
        """
name: Windows CI
jobs:
  android:
    steps:
      - name: Detect release APK scope
        id: release-apk-scope
        run: |
          function Set-ReleaseApkRequired([string]$value) {
            [System.IO.File]::AppendAllText(
              $env:GITHUB_OUTPUT,
              "release_apk_required=$value`n",
              [System.Text.UTF8Encoding]::new($false)
            )
          }
          $eventName = "${{ github.event_name }}"
          $refName = "${{ github.ref_name }}"
          if ($eventName -eq "workflow_dispatch" -or $refName -eq "main") {
            Set-ReleaseApkRequired "true"
            exit 0
          }
          $changed = @(git diff --name-only origin/main...HEAD)
          if ($LASTEXITCODE -ne 0) {
            $changed = @(git diff --name-only origin/main HEAD)
          }
          if ($LASTEXITCODE -ne 0) {
            throw "Unable to compute changed files against origin/main"
          }
          $releaseRelevant = $changed | Where-Object {
            $_ -match '^(android/|\\.github/workflows/|\\.gitea/workflows/)'
          } | Select-Object -First 1
          if ($releaseRelevant) {
            Write-Host "release relevant"
          }
          if ($false) {
            Set-ReleaseApkRequired "true"
          } else {
            Set-ReleaseApkRequired "false"
          }
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: .\\gradlew.bat --no-daemon :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({github, ci}) == [_GITEA_POLICY]

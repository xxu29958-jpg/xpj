from __future__ import annotations

from pathlib import Path


def write_valid_github(tmp_path: Path) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    ci = workflows / "ci.yml"
    ci.write_text(
        """
name: CI
jobs:
  android:
    steps:
      - name: Detect release APK scope
        id: release-apk-scope
        run: |
          if [ "${{ github.event_name }}" != "pull_request" ]; then
            echo "release_apk_required=true" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          base="${{ github.event.pull_request.base.sha }}"
          head="${{ github.event.pull_request.head.sha }}"
          changed="$(git diff --name-only "${base}...${head}")"
          if printf '%s\\n' "$changed" | grep -E '^(android/|\\.github/workflows/|\\.gitea/workflows/)' >/dev/null; then
            echo "release_apk_required=true" >> "$GITHUB_OUTPUT"
          else
            echo "release_apk_required=false" >> "$GITHUB_OUTPUT"
          fi
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    return ci


def write_valid_gitea(tmp_path: Path) -> Path:
    workflows = tmp_path / ".gitea" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
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
    return ci


def write_github_heredoc_forgery(tmp_path: Path, *, multiple: bool = False) -> Path:
    ci = tmp_path / ".github" / "workflows" / "ci.yml"
    opener = ": <<'FORGED_GATE' <<'SECOND_GATE'" if multiple else ": <<'FORGED_GATE'"
    first_close = "FORGED_GATE\n          ignored first body" if multiple else ""
    second_close = "SECOND_GATE" if multiple else "FORGED_GATE"
    ci.write_text(
        f"""
name: CI
jobs:
  android:
    steps:
      - name: Detect release APK scope
        id: release-apk-scope
        run: |
          {opener}
          {first_close}
          if [ "${{{{ github.event_name }}}}" != "pull_request" ]; then
            echo "release_apk_required=true" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          base="${{{{ github.event.pull_request.base.sha }}}}"
          head="${{{{ github.event.pull_request.head.sha }}}}"
          changed="$(git diff --name-only "${{base}}...${{head}}")"
          if printf '%s\\n' "$changed" | grep -E '^(android/|\\.github/workflows/|\\.gitea/workflows/)' >/dev/null; then
            echo "release_apk_required=true" >> "$GITHUB_OUTPUT"
          else
            echo "release_apk_required=false" >> "$GITHUB_OUTPUT"
          fi
          {second_close}
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    return ci


def write_gitea_here_string_forgery(tmp_path: Path) -> Path:
    ci = tmp_path / ".gitea" / "workflows" / "windows-ci.yml"
    ci.write_text(
        """
name: Windows CI
jobs:
  android:
    steps:
      - name: Detect release APK scope
        id: release-apk-scope
        run: |
          $forgedGate = @'
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
            Set-ReleaseApkRequired "true"
          } else {
            Set-ReleaseApkRequired "false"
          }
          '@
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: .\\gradlew.bat --no-daemon :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )
    return ci

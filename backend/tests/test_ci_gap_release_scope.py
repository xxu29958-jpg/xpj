from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci_gap_release_scope.py"
_GITHUB_POLICY = (
    ".github/workflows/ci.yml: Android release APK builds must be path-gated for non-Android changes"
)
_GITEA_POLICY = (
    ".gitea/workflows/windows-ci.yml: Android release APK builds must be path-gated for non-Android changes"
)
_MISSING_GITHUB = ".github/workflows/ci.yml: required workflow missing from CI gap scan"
_MISSING_GITEA = ".gitea/workflows/windows-ci.yml: required workflow missing from CI gap scan"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("ci_gap_release_scope", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_valid_github(tmp_path: Path) -> Path:
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


def _write_valid_gitea(tmp_path: Path) -> Path:
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


def test_ci_gap_release_apk_scope_policy_accepts_pr_path_gate(tmp_path: Path) -> None:
    mod = _load()
    github = _write_valid_github(tmp_path)
    gitea = _write_valid_gitea(tmp_path)

    assert mod.release_apk_scope_policy_violations({github, gitea}) == []


def test_ci_gap_release_apk_scope_policy_rejects_missing_expected_workflows() -> None:
    mod = _load()

    assert mod.release_apk_scope_policy_violations(set()) == [_MISSING_GITHUB, _MISSING_GITEA]


def test_ci_gap_release_apk_scope_policy_rejects_unconditional_pr_release_build(
    tmp_path: Path,
) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    ci = workflows / "ci.yml"
    ci.write_text(
        """
name: CI
jobs:
  android:
    steps:
      - name: Android release APK builds
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_comment_only_gate(tmp_path: Path) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    ci = workflows / "ci.yml"
    ci.write_text(
        """
name: CI
jobs:
  android:
    steps:
      - name: stale note
        run: |
          # id: release-apk-scope
          # if: steps.release-apk-scope.outputs.release_apk_required == 'true'
          echo "release_apk_required=true"
          echo "release_apk_required=false"
          echo "github.event_name pull_request git diff --name-only ${base}...${head}"
          echo "android/ .github/workflows/ .gitea/workflows/"
      - name: Android release APK builds
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_active_github_string_forgery(
    tmp_path: Path,
) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
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
          echo "release_apk_required=true"
          echo "release_apk_required=false"
          echo "github.event_name pull_request github.event.pull_request.base.sha github.event.pull_request.head.sha"
          echo "git diff --name-only ${base}...${head} grep -E android/ .github/workflows/ .gitea/workflows/"
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_github_output_prefix_spoof(
    tmp_path: Path,
) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
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
            echo "release_apk_required=true" >> "$GITHUB_OUTPUT_DISABLED"
            exit 0
          fi
          base="${{ github.event.pull_request.base.sha }}"
          head="${{ github.event.pull_request.head.sha }}"
          changed="$(git diff --name-only "${base}...${head}")"
          if printf '%s\\n' "$changed" | grep -E '^(android/|\\.github/workflows/|\\.gitea/workflows/)' >/dev/null; then
            echo "release_apk_required=true" >> "$GITHUB_OUTPUT_DISABLED"
          else
            echo "release_apk_required=false" >> "$GITHUB_OUTPUT_DISABLED"
          fi
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_single_quoted_github_output(
    tmp_path: Path,
) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
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
            echo "release_apk_required=true" >> '$GITHUB_OUTPUT'
            exit 0
          fi
          base="${{ github.event.pull_request.base.sha }}"
          head="${{ github.event.pull_request.head.sha }}"
          changed="$(git diff --name-only "${base}...${head}")"
          if printf '%s\\n' "$changed" | grep -E '^(android/|\\.github/workflows/|\\.gitea/workflows/)' >/dev/null; then
            echo "release_apk_required=true" >> '$GITHUB_OUTPUT'
          else
            echo "release_apk_required=false" >> '$GITHUB_OUTPUT'
          fi
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_github_echoed_logic_tokens(
    tmp_path: Path,
) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
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
          echo "release_apk_required=true" >> "$GITHUB_OUTPUT"
          echo "release_apk_required=false" >> "$GITHUB_OUTPUT"
          echo 'if [ "${{ github.event_name }}" != "pull_request" ]; then'
          echo 'base="${{ github.event.pull_request.base.sha }}"'
          echo 'head="${{ github.event.pull_request.head.sha }}"'
          echo 'changed="$(git diff --name-only "${base}...${head}")"'
          echo "if printf '%s\\n' \"$changed\" | grep -E '^(android/|\\.github/workflows/|\\.gitea/workflows/)' >/dev/null; then"
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_github_echoed_output_writes(
    tmp_path: Path,
) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
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
            echo 'echo "release_apk_required=true" >> "$GITHUB_OUTPUT"'
            exit 0
          fi
          base="${{ github.event.pull_request.base.sha }}"
          head="${{ github.event.pull_request.head.sha }}"
          changed="$(git diff --name-only "${base}...${head}")"
          if printf '%s\\n' "$changed" | grep -E '^(android/|\\.github/workflows/|\\.gitea/workflows/)' >/dev/null; then
            echo 'echo "release_apk_required=true" >> "$GITHUB_OUTPUT"'
          else
            echo 'echo "release_apk_required=false" >> "$GITHUB_OUTPUT"'
          fi
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_disconnected_github_output_writes(
    tmp_path: Path,
) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
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
          echo "release_apk_required=true" >> "$GITHUB_OUTPUT"
          echo "release_apk_required=false" >> "$GITHUB_OUTPUT"
          if [ "${{ github.event_name }}" != "pull_request" ]; then
            echo "non-PR event"
            exit 0
          fi
          base="${{ github.event.pull_request.base.sha }}"
          head="${{ github.event.pull_request.head.sha }}"
          changed="$(git diff --name-only "${base}...${head}")"
          if printf '%s\\n' "$changed" | grep -E '^(android/|\\.github/workflows/|\\.gitea/workflows/)' >/dev/null; then
            echo "Android/CI change"
          else
            echo "backend-only change"
          fi
      - name: Android release APK builds
        if: steps.release-apk-scope.outputs.release_apk_required == 'true'
        run: ./gradlew --no-daemon --max-workers=1 :app:assembleGrayRelease :app:assembleInternalRelease
""",
        encoding="utf-8",
    )

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_unreachable_github_path_gate(
    tmp_path: Path,
) -> None:
    mod = _load()
    gitea = _write_valid_gitea(tmp_path)
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
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
          exit 0
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

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]

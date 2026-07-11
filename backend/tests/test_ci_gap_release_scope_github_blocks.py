from __future__ import annotations

from pathlib import Path

from test_ci_gap_release_scope import _GITHUB_POLICY, _load

from tests._infra.ci_gap_release_scope import write_valid_gitea as _write_valid_gitea


def test_ci_gap_release_apk_scope_policy_rejects_github_non_pr_block_hop(
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
            echo "forgot output"
          fi
          if true; then
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

    assert mod.release_apk_scope_policy_violations({ci, gitea}) == [_GITHUB_POLICY]


def test_ci_gap_release_apk_scope_policy_rejects_github_path_block_hop(
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
          base="${{ github.event.pull_request.base.sha }}"
          head="${{ github.event.pull_request.head.sha }}"
          changed="$(git diff --name-only "${base}...${head}")"
          if printf '%s\\n' "$changed" | grep -E '^(android/|\\.github/workflows/|\\.gitea/workflows/)' >/dev/null; then
            echo "release relevant"
          fi
          if false; then
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

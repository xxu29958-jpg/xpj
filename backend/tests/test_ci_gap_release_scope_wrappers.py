from __future__ import annotations

from pathlib import Path

import pytest
from test_ci_gap_release_scope import _GITEA_POLICY, _GITHUB_POLICY, _load

from tests._infra.ci_gap_release_scope import write_valid_gitea, write_valid_github


def _wrap_detector_body(path: Path, *, opener: str, closer: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    run_index = next(
        index
        for index, line in enumerate(lines)
        if line.strip() == "run: |" and "Detect release APK scope" in lines[index - 2]
    )
    next_step = next(
        index
        for index in range(run_index + 1, len(lines))
        if lines[index].startswith("      - name: Android release APK builds")
    )
    body = [f"  {line}" for line in lines[run_index + 1 : next_step]]
    lines[run_index + 1 : next_step] = [f"          {opener}", *body, f"          {closer}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("platform", "opener", "closer", "expected"),
    [
        ("github", "if false; then", "fi", _GITHUB_POLICY),
        ("gitea", "if ($false) {", "}", _GITEA_POLICY),
    ],
)
def test_release_scope_rejects_valid_detector_hidden_in_false_wrapper(
    tmp_path: Path,
    platform: str,
    opener: str,
    closer: str,
    expected: str,
) -> None:
    github = write_valid_github(tmp_path)
    gitea = write_valid_gitea(tmp_path)
    target = github if platform == "github" else gitea
    _wrap_detector_body(target, opener=opener, closer=closer)

    assert _load().release_apk_scope_policy_violations({github, gitea}) == [expected]

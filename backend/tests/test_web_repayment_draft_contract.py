"""Execute the shipped repayment form and its browser lease/storage consumers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", [
    "continuity", "binding_and_lease", "validation", "ack", "storage", "removed", "replacement", "blocked_recovery",
])
def test_repayment_original_submission_survives_browser_lifecycle(scenario: str) -> None:
    node = shutil.which("node")
    assert node is not None, "The web contract lane requires Node"
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [node, str(root / "tests/fixtures/repayment_draft_contract.cjs"),
         str(root / "app/static/web/manual-drafts.js"),
         str(root / "app/static/web/repayment-entry.js"), scenario],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr

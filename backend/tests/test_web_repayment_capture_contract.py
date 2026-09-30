"""Execute the shipped capture review against browser lifecycle and identity changes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["continuity", "rejectionAndBinding", "parentSubmission"])
def test_capture_original_survives_browser_lifecycle(scenario: str) -> None:
    node = shutil.which("node")
    assert node is not None, "The web contract lane requires Node"
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [node, str(root / "tests/fixtures/repayment_capture_review_contract.cjs"),
         str(root / "app/static/web/manual-drafts.js"),
         str(root / "app/static/web/repayment-entry.js"), scenario],
        capture_output=True, text=True, encoding="utf-8", timeout=10,
    )
    assert result.returncode == 0, result.stderr

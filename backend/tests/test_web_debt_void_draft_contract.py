"""Run actual shipped void producers with the shared storage/lease consumer."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", ["debt-void", "repayment-void"])
def test_void_original_submission_survives_browser_storage_and_exact_ack(kind):
    root = Path(__file__).parents[1]
    result = subprocess.run([shutil.which("node"), str(root / "tests/fixtures/debt_void_draft_contract.cjs"),
        str(root / "app/static/web/manual-drafts.js"), str(root / "app/static/web/repayment-entry.js"), kind],
        capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr

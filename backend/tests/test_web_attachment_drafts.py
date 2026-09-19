"""Execute the existing draft owner with its attachment/file continuation adapter."""

import shutil
import subprocess
from pathlib import Path


def test_attachment_intent_retains_original_file_binding_and_ack_boundary():
    node = shutil.which("node")
    assert node is not None
    root = Path(__file__).parents[1]
    result = subprocess.run([node, str(root / "tests/fixtures/attachment_draft_contract.cjs"),
        str(root / "app/static/web")], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr

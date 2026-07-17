from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.parallel_safe


def test_hard_cleanup_waits_for_disposable_file_creation(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    target = tmp_path / "derived-secret"
    probe = """
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from scripts.test_pg_disposable_file import (
    _remove_disposable_test_files,
    disposable_test_file_cleanup,
)

target = Path(sys.argv[2]).resolve()
creation_entered = threading.Event()
release_creation = threading.Event()
errors = []
cleanup_result = []

with disposable_test_file_cleanup(target) as reservation:
    def create_file():
        try:
            with reservation.creation():
                creation_entered.set()
                if not release_creation.wait(2):
                    raise RuntimeError("creation release timed out")
                target.write_text("secret", encoding="utf-8")
        except BaseException as exc:
            errors.append(exc)
            creation_entered.set()

    creator = threading.Thread(target=create_file)
    creator.start()
    if not creation_entered.wait(2):
        raise RuntimeError("creation did not enter")
    if errors:
        raise errors[0]
    cleaner = threading.Thread(
        target=lambda: cleanup_result.append(_remove_disposable_test_files())
    )
    cleaner.start()
    time.sleep(0.05)
    if not cleaner.is_alive():
        raise RuntimeError("hard cleanup did not wait for creation")
    release_creation.set()
    creator.join(2)
    cleaner.join(2)
    if creator.is_alive() or cleaner.is_alive():
        raise RuntimeError("disposable file synchronization deadlocked")
    if errors:
        raise errors[0]
    if cleanup_result != [()]:
        raise RuntimeError(f"cleanup failed: {cleanup_result!r}")
    if target.exists():
        raise RuntimeError("hard cleanup stranded the disposable file")
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe, str(backend_root), str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_disposable_file_creation_is_rejected_after_hard_cleanup(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    target = tmp_path / "late-derived-secret"
    probe = """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from scripts.test_pg_disposable_file import (
    _remove_disposable_test_files,
    disposable_test_file_cleanup,
)

target = Path(sys.argv[2]).resolve()
with disposable_test_file_cleanup(target) as reservation:
    if _remove_disposable_test_files() != ():
        raise RuntimeError("empty cleanup unexpectedly failed")
    try:
        with reservation.creation():
            target.write_text("secret", encoding="utf-8")
    except RuntimeError as error:
        if "cleanup has already started" not in str(error):
            raise
    else:
        raise RuntimeError("late secret creation was accepted")
if target.exists():
    raise RuntimeError("late secret was created after cleanup")
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe, str(backend_root), str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr

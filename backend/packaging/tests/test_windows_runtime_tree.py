from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle-bound deletion")
def test_windows_runtime_delete_pins_the_opened_root(tmp_path: Path) -> None:
    from tests._infra.windows_tree import remove_tree_exact

    target = tmp_path / "runtime"
    target.mkdir()
    (target / "artifact").write_text("owned", encoding="utf-8")
    moved = tmp_path / "moved"

    def attempt_root_swap(opened: Path) -> None:
        with pytest.raises(OSError):
            opened.rename(moved)

    remove_tree_exact(target, on_root_opened=attempt_root_swap)

    assert not target.exists()
    assert not moved.exists()

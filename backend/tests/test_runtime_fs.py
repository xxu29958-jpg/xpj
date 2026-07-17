from __future__ import annotations

from pathlib import Path

import pytest

from tests._infra import runtime_fs

pytestmark = pytest.mark.parallel_safe


def test_runtime_tree_cleanup_is_bounded_owned_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    owned_root = tmp_path / "runtime"
    owned_root.mkdir()
    target = owned_root / "run-identity"
    target.mkdir()
    (target / "state.txt").write_text("owned", encoding="ascii")

    runtime_fs.remove_owned_runtime_tree(
        target,
        owned_root=owned_root,
        label="Test runtime",
    )
    assert not target.exists()
    runtime_fs.remove_owned_runtime_tree(
        target,
        owned_root=owned_root,
        label="Test runtime",
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(RuntimeError, match="outside its declared runtime root"):
        runtime_fs.remove_owned_runtime_tree(
            outside,
            owned_root=owned_root,
            label="Test runtime",
        )

    target.mkdir()
    monkeypatch.setattr(
        runtime_fs.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(PermissionError("locked")),
    )
    with pytest.raises(RuntimeError, match="still exists after bounded cleanup"):
        runtime_fs.remove_owned_runtime_tree(
            target,
            owned_root=owned_root,
            label="Test runtime",
            attempts=2,
            retry_delay_seconds=0,
        )
    assert target.exists()

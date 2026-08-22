"""Crash-durable tree and file publication mechanism contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import durable_publication


def test_plain_tree_is_flushed_before_write_through_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = (tmp_path / "staging").resolve()
    target = (tmp_path / "current").resolve()
    payload = staging / "nested" / "payload.bin"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"durable-payload")
    events: list[tuple[str, str]] = []
    real_flush = durable_publication._flush_regular_file
    real_move = durable_publication._move_windows

    def record_flush(path: Path) -> None:
        events.append(("flush", path.name))
        real_flush(path)

    def record_move(source: Path, destination: Path, *, replace: bool) -> None:
        events.append(("move", destination.name))
        real_move(source, destination, replace=replace)

    monkeypatch.setattr(durable_publication, "_flush_regular_file", record_flush)
    if durable_publication.os.name == "nt":
        monkeypatch.setattr(durable_publication, "_move_windows", record_move)

    durable_publication.publish_durable_tree(staging, target)

    assert (target / "nested" / "payload.bin").read_bytes() == b"durable-payload"
    if durable_publication.os.name == "nt":
        assert events == [("flush", "payload.bin"), ("move", "current")]


def test_tree_flush_failure_leaves_target_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = (tmp_path / "staging").resolve()
    target = (tmp_path / "current").resolve()
    staging.mkdir()
    (staging / "payload.bin").write_bytes(b"payload")

    def fail_flush(_path: Path) -> None:
        raise OSError("flush failed")

    monkeypatch.setattr(durable_publication, "_flush_regular_file", fail_flush)

    with pytest.raises(OSError, match="flush failed"):
        durable_publication.publish_durable_tree(staging, target)

    assert staging.is_dir()
    assert not target.exists()


def test_durable_file_replacement_publishes_exact_staging_bytes(tmp_path: Path) -> None:
    target = (tmp_path / "inventory.json").resolve()
    staging = (tmp_path / ".inventory.json.staging").resolve()
    target.write_bytes(b"old")
    staging.write_bytes(b"new")

    durable_publication.replace_durable_file(staging, target)

    assert target.read_bytes() == b"new"
    assert not staging.exists()

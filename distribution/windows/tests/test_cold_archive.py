from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from ticketbox_lifecycle import cli
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import cold_archive


@pytest.fixture
def materials(tmp_path: Path) -> dict[str, Path]:
    roots = {name: tmp_path / "original" / name for name in cold_archive.COMPONENTS}
    for root in roots.values():
        root.mkdir(parents=True)
    (roots["data/pgdata"] / "pg_wal").mkdir()
    (roots["data/pgdata"] / "financial-facts").write_bytes(b"amount=1234;revision=9;dataset=original")
    (roots["data/attachments"] / "receipt.png").write_bytes(b"retained-original-image")
    (roots["machine"] / "installation.json").write_text('{"install_id":"original-install"}')
    (roots["data/app"] / ".env").write_bytes(b"fixture-only-private-credential")
    (roots["program"] / "release-manifest.json").write_bytes(b"exact-release")
    for name in ("PG_VERSION", "global/pg_control"):
        file = roots["data/pgdata"] / name
        file.parent.mkdir(exist_ok=True)
        file.write_bytes(b"17" if name == "PG_VERSION" else b"control")
    secrets = roots["machine"] / "secrets"
    secrets.mkdir()
    for name in ("postgres.password", "ticketbox_migrator.password", "ticketbox_runtime.password", "pgpass"):
        (secrets / name).write_bytes(b"fixture-only-secret")
    return roots


def _write(path: Path, roots: dict[str, Path], checkpoint) -> dict[str, object]:
    with path.open("x+b") as target:
        return cold_archive.write_archive(target, roots, {"dataset_id": "original"}, checkpoint)


def test_retention_reopens_with_every_original_file_and_empty_directory(
    tmp_path: Path, materials: dict[str, Path], capsys,
) -> None:
    checks: list[str] = []
    target = tmp_path / "new.tbxcold"
    result = _write(target, materials, lambda: checks.append("stopped"))
    assert checks == ["stopped", "stopped"]
    assert result["files"] == 11
    assert cli.main(["verify-cold-copy", "--source", str(target)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True and output["identity"] == {"dataset_id": "original"}
    assert "credential" not in json.dumps(output)
    with zipfile.ZipFile(target) as archive:
        assert archive.read("data/app/.env") == b"fixture-only-private-credential"
        assert archive.read("data/pgdata/financial-facts") == b"amount=1234;revision=9;dataset=original"
        assert archive.read("data/attachments/receipt.png") == (materials["data/attachments"] / "receipt.png").read_bytes()
        assert "data/pgdata/pg_wal/" in archive.namelist()


@pytest.mark.parametrize("change", ["rewrite", "new_file", "restart"])
def test_source_change_or_restart_never_seals_a_partial_copy(
    tmp_path: Path, materials: dict[str, Path], monkeypatch, change: str,
) -> None:
    original_copy = cold_archive._copy_file
    altered = False

    def copy_then_change(*args):
        nonlocal altered
        result = original_copy(*args)
        if not altered:
            altered = True
            if change == "rewrite":
                Path(args[2]).write_bytes(b"new-source-value")
            elif change == "new_file":
                (materials["data/app"] / "later").write_bytes(b"later")
        return result

    def checkpoint():
        if change == "restart" and altered:
            raise LifecycleError("cold_services_running", "restarted during copy")

    monkeypatch.setattr(cold_archive, "_copy_file", copy_then_change)
    target = tmp_path / "partial.tbxcold"
    with pytest.raises(LifecycleError, match="changed|restarted"):
        _write(target, materials, checkpoint)
    with target.open("rb") as stream, pytest.raises(LifecycleError, match="completion manifest"):
        cold_archive.verify_archive(stream)


def test_byte_corruption_and_truncation_are_not_accepted_as_cold_copies(
    tmp_path: Path, materials: dict[str, Path], capsys,
) -> None:
    target = tmp_path / "cold.tbxcold"
    observed: list[bool] = []
    _write(target, materials, lambda: observed.append(True))
    original = target.read_bytes()
    with zipfile.ZipFile(target) as archive:
        entry = archive.getinfo("data/attachments/receipt.png")
        local_header = original[entry.header_offset:entry.header_offset + 30]
        offset = entry.header_offset + 30 + int.from_bytes(local_header[26:28], "little") + int.from_bytes(local_header[28:30], "little")
    corrupt = bytearray(original)
    corrupt[offset] ^= 0x01
    target.write_bytes(corrupt)
    assert cli.main(["verify-cold-copy", "--source", str(target)]) == 2
    assert json.loads(capsys.readouterr().err)["ok"] is False
    target.write_bytes(original[:-24])
    assert cli.main(["verify-cold-copy", "--source", str(target)]) == 2


def test_explicit_retry_uses_a_new_file_and_preserves_the_previous_copy(
    tmp_path: Path, materials: dict[str, Path],
) -> None:
    target = tmp_path / "retained.tbxcold"
    checks: list[bool] = []
    _write(target, materials, lambda: checks.append(True))
    before = hashlib.sha256(target.read_bytes()).digest()
    with pytest.raises(FileExistsError):
        _write(target, materials, lambda: checks.append(False))
    assert hashlib.sha256(target.read_bytes()).digest() == before
    assert checks == [True, True]


def test_read_failure_or_missing_source_cannot_publish_completion(
    tmp_path: Path, materials: dict[str, Path], monkeypatch,
) -> None:
    def denied(*_args):
        raise PermissionError("fixture denial")

    monkeypatch.setattr(cold_archive, "_copy_file", denied)
    target = tmp_path / "denied.tbxcold"
    observed: list[bool] = []
    with pytest.raises(PermissionError):
        _write(target, materials, lambda: observed.append(True))
    with zipfile.ZipFile(target) as archive:
        assert cold_archive.MANIFEST not in archive.namelist()
    materials["data/pgdata"] = tmp_path / "missing-pgdata"
    with pytest.raises(LifecycleError, match="required cold copy directory"):
        _write(tmp_path / "missing.tbxcold", materials, lambda: observed.append(True))

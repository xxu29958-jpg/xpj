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
    assert "fixture-only-private-credential" not in json.dumps(output)
    assert output["public_connectivity"]["credentials"] == "not_backed_up"
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


def test_new_copy_excludes_entire_connector_secret_authority_and_keeps_database_material(tmp_path, materials):
    secrets = materials["machine"] / "connectors/cloudflare/secrets"
    secrets.mkdir(parents=True)
    for name in ("active", "pending", "previous", "generation-7/value.bin"):
        target = secrets / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture-tunnel-private")
    record = secrets.parent / "state.json"
    record.write_text('{"configured":true}')
    archive_path = tmp_path / "without-tunnel.tbxcold"
    result = _write(archive_path, materials, lambda: None)
    assert result["schema"] == cold_archive.SCHEMA
    with zipfile.ZipFile(archive_path) as archive:
        assert not any("connectors/cloudflare/secrets" in name for name in archive.namelist())
        assert archive.read("machine/connectors/cloudflare/state.json") == record.read_bytes()
        assert archive.read("machine/secrets/postgres.password") == b"fixture-only-secret"
    with archive_path.open("rb") as stream:
        assert cold_archive.verify_archive(stream) == result


@pytest.mark.parametrize("schema", [cold_archive.LEGACY_SCHEMA, cold_archive.SCHEMA])
def test_legacy_copy_keeps_its_original_policy_but_new_format_cannot_smuggle_tunnel_secret(tmp_path, materials, schema):
    original = tmp_path / "new.tbxcold"
    _write(original, materials, lambda: None)
    candidate = tmp_path / "fixture.tbxcold"
    with zipfile.ZipFile(original) as old, zipfile.ZipFile(candidate, "w") as new:
        manifest = json.loads(old.read(cold_archive.MANIFEST))
        for name in old.namelist():
            if name != cold_archive.MANIFEST:
                new.writestr(name, old.read(name))
        name = "machine/connectors/cloudflare/secrets/previous"
        raw = b"historical-fixture-tunnel"
        new.writestr(name, raw)
        manifest["entries"][name] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        manifest["schema"] = schema
        if schema == cold_archive.LEGACY_SCHEMA:
            manifest.pop("public_connectivity")
        new.writestr(cold_archive.MANIFEST, json.dumps(manifest))
    before = candidate.read_bytes()
    with candidate.open("rb") as stream:
        if schema == cold_archive.LEGACY_SCHEMA:
            result = cold_archive.verify_archive(stream)
            assert result["public_connectivity"]["credentials"] == "legacy_unspecified"
        else:
            with pytest.raises(LifecycleError, match="exclude"):
                cold_archive.verify_archive(stream)
    assert candidate.read_bytes() == before

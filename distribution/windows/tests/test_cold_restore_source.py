from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime.cold_archive import COMPONENTS, write_archive
from ticketbox_lifecycle.runtime.cold_restore_source import ColdRestoreSource
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, InstallRequest


@pytest.fixture
def source(tmp_path):
    roots = {name: tmp_path / "source" / name for name in COMPONENTS}
    for root in roots.values():
        root.mkdir(parents=True)
    files = {
        "data/pgdata/PG_VERSION": b"17\n",
        "data/pgdata/global/pg_control": b"stopped-cluster",
        "data/pgdata/base/facts": b"amount=1234;revision=9;receipt=original",
        "data/app/.env": b"old-credentials-stay-in-backup",
        "data/app/uploads/receipt.jpg": b"original-receipt",
        "program/postgresql/bin/postgres.exe": b"trusted-pg",
        "program/releases/1.2.0/backend/backend.exe": b"old-program-never-executed",
    }
    inventory = []
    for name, raw in files.items():
        path = tmp_path / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        if name.startswith("program/"):
            inventory.append({"path": name[8:], "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    release = json.dumps({"release_id": "1.2.0", "max_schema_revision": "20261023_0002",
        "min_semantic_revision": "ticketbox-dataset-semantics-v1", "immutable_payload": {"files": inventory}}).encode()
    (roots["program"] / "releases/1.2.0/release-manifest.json").write_bytes(release)
    identity = {"install_id": "012f39a1-3d82-4b4a-89b7-3b8e80adbed5",
        "dataset_id": "f7db99e3-dd48-4791-83f4-edfbe451e47a", "restore_epoch": 0,
        "release_id": "1.2.0", "schema_revision": "20261023_0002", "postgres_major": 17,
        "release_manifest_sha256": hashlib.sha256(release).hexdigest()}
    (roots["machine"] / "installation.json").write_text(json.dumps({
        "schema": "ticketbox-installed-instance-v1", **identity, "expected_restore_epoch": 0}))
    history = roots["machine"] / "operations/history/source.json"
    history.parent.mkdir(parents=True)
    history.write_text(json.dumps({"schema": "ticketbox-lifecycle-operation-v2", "phase": "committed",
        "operation_id": "source-install", **identity}))
    secret_root = roots["machine"] / "secrets"
    secret_root.mkdir()
    for name in ("postgres.password", "ticketbox_migrator.password", "ticketbox_runtime.password", "pgpass"):
        (secret_root / name).write_bytes(b"fixture-only-secret")
    target = tmp_path / "source.tbxcold"
    with target.open("x+b") as stream:
        write_archive(stream, roots, identity, lambda: None)
    request = InstallRequest(REQUEST_SCHEMA, "install", "fixture", "fixture", "1.2.0", str(roots["program"]),
        str(tmp_path / "new-data"), str(tmp_path / "new-install"), "TicketboxPg", "TicketboxBackend", 5432, 8000, 17,
        "new-release", schema_revision="20261023_0002", semantic_revision="ticketbox-dataset-semantics-v1")
    return target, request


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_restore_copies_facts_and_originals_without_adopting_archived_program_or_binding(source):
    path, request = source
    original = path.read_bytes()
    destination = Path(request.data_root)
    with path.open("rb") as stream:
        candidate = ColdRestoreSource(stream, _digest(path), request)
        candidate.extract_data(destination)
    assert path.read_bytes() == original
    assert (destination / "pgdata/base/facts").read_bytes() == b"amount=1234;revision=9;receipt=original"
    assert (destination / "app/uploads/receipt.jpg").read_bytes() == b"original-receipt"
    assert not (destination.parent / "machine").exists()
    assert not (destination / "program").exists()
    with path.open("rb") as stream:
        replay = ColdRestoreSource(stream, _digest(path), request)
        assert replay.backup_id == candidate.backup_id
        with pytest.raises(LifecycleError, match="new data directory"):
            replay.extract_data(destination)


@pytest.mark.parametrize("mismatch", ["hash", "schema", "postgres"])
def test_mismatch_refuses_before_any_target_write(source, mismatch):
    path, request = source
    digest = _digest(path)
    original = path.read_bytes()
    if mismatch == "hash":
        digest = "0" * 64
    elif mismatch == "schema":
        request = replace(request, schema_revision="20261001_0001")
    else:
        (Path(request.app_dir) / "postgresql/bin/postgres.exe").write_bytes(b"different-postgres")
    with path.open("rb") as stream, pytest.raises(LifecycleError):
        ColdRestoreSource(stream, digest, request)
    assert not Path(request.data_root).exists()
    assert path.read_bytes() == original


@pytest.mark.parametrize("name", ["data/app/../../escaped", "data/app/CON.txt", "data/app/.env:secret", "DATA/APP/.ENV"])
def test_windows_archive_aliases_cannot_escape_or_replace_candidate(source, name):
    path, request = source
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(name, b"unsafe")
    with path.open("rb") as stream, pytest.raises(LifecycleError, match="unsafe Windows"):
        ColdRestoreSource(stream, _digest(path), request)
    assert not Path(request.data_root).exists()


def test_interrupted_copy_preserves_source_and_does_not_reuse_partial_target(source, monkeypatch):
    import ticketbox_lifecycle.runtime.cold_restore_source as module

    path, request = source
    original = path.read_bytes()
    destination = Path(request.data_root)

    def interrupt(source, output, **kwargs):
        output.write(source.read(2))
        raise OSError("injected copy interruption")

    monkeypatch.setattr(module.shutil, "copyfileobj", interrupt)
    with path.open("rb") as stream:
        candidate = ColdRestoreSource(stream, _digest(path), request)
        with pytest.raises(OSError, match="interruption"):
            candidate.extract_data(destination)
        with pytest.raises(LifecycleError, match="new data directory"):
            candidate.extract_data(destination)
    assert path.read_bytes() == original
    assert destination.is_dir()

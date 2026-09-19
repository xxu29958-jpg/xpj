"""Original reads bind consumers to the checked bytes without changing metadata."""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import contextmanager
from functools import partial
from types import SimpleNamespace

import pytest

from app.errors import AppError
from app.services import file_service, original_read_service

ORIGINAL = b"stored post-sanitation original"


@pytest.fixture
def original_store(monkeypatch, tmp_path):
    uploads = tmp_path / "uploads"
    original = uploads / "owner" / "receipt.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(ORIGINAL)
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    monkeypatch.setattr(file_service, "get_settings", lambda: SimpleNamespace(upload_dir=uploads))
    monkeypatch.setattr(original_read_service, "TemporaryDirectory", partial(tempfile.TemporaryDirectory, dir=snapshots))
    return original, snapshots


def _read(expected_sha256):
    return original_read_service.read_original_snapshot(
        relative_path="uploads/owner/receipt.png", tenant_id="owner", expected_sha256=expected_sha256,
    )


def test_checked_snapshot_survives_original_removal_and_closes(original_store):
    original, snapshots = original_store
    digest = hashlib.sha256(ORIGINAL).hexdigest()
    with _read(digest.upper()) as snapshot:
        original.unlink()
        assert snapshot.path.read_bytes() == ORIGINAL
        assert (snapshot.sha256, snapshot.size_bytes, snapshot.verified) == (digest, len(ORIGINAL), True)
        assert snapshot.media_type == "image/png"
    assert not list(snapshots.iterdir())
    snapshot.close()


@pytest.mark.parametrize("expected", [None, "", "legacy", "g" * 64])
def test_unusable_legacy_digest_is_readable_without_rewriting_identity(original_store, expected):
    original, snapshots = original_store
    with _read(expected) as snapshot:
        assert snapshot.verified is False
        assert snapshot.path.read_bytes() == ORIGINAL
        assert snapshot.sha256 == hashlib.sha256(ORIGINAL).hexdigest()
    assert original.read_bytes() == ORIGINAL
    assert not list(snapshots.iterdir())


def test_digest_mismatch_leaves_no_partial_snapshot(original_store):
    original, snapshots = original_store
    original.write_bytes(b"replaced original")
    with pytest.raises(AppError) as rejected:
        _read(hashlib.sha256(ORIGINAL).hexdigest())
    assert rejected.value.error == "image_integrity_mismatch"
    assert original.read_bytes() == b"replaced original"
    assert not list(snapshots.iterdir())


@pytest.mark.parametrize("reference", [None, "uploads/owner/missing.png", "uploads/elsewhere/receipt.png", "../receipt.png"])
def test_missing_or_out_of_scope_reference_creates_no_snapshot(original_store, reference):
    original, snapshots = original_store
    other = original.parents[1] / "elsewhere" / "receipt.png"
    other.parent.mkdir()
    other.write_bytes(ORIGINAL)
    with pytest.raises(AppError) as rejected:
        original_read_service.read_original_snapshot(relative_path=reference, tenant_id="owner", expected_sha256=None)
    assert rejected.value.error == "image_not_found"
    assert not list(snapshots.iterdir())


def test_default_ledger_legacy_path_remains_readable(original_store):
    original, _ = original_store
    legacy = original.parents[1] / "2020" / "01" / "receipt.png"
    legacy.parent.mkdir(parents=True)
    original.replace(legacy)
    with original_read_service.read_original_snapshot(
        relative_path="uploads/2020/01/receipt.png", tenant_id="owner", expected_sha256=None,
    ) as snapshot:
        assert snapshot.path.read_bytes() == ORIGINAL
        assert snapshot.verified is False
    with pytest.raises(AppError):
        original_read_service.read_original_snapshot(
            relative_path="uploads/2020/01/receipt.png", tenant_id="other", expected_sha256=None,
        )


def test_hardlinked_original_is_not_consumed(original_store):
    original, snapshots = original_store
    os.link(original, original.with_name("second-link.png"))
    with pytest.raises(AppError):
        _read(hashlib.sha256(ORIGINAL).hexdigest())
    assert not list(snapshots.iterdir())


def test_source_read_failure_removes_partial_snapshot(original_store, monkeypatch):
    _, snapshots = original_store
    real_reader = original_read_service.hold_stable_file_for_read

    @contextmanager
    def interrupted_reader(path):
        with real_reader(path) as source:
            def read(_size):
                if source.tell() > 0:
                    raise OSError("synthetic interrupted read")
                return source.read(4)
            yield SimpleNamespace(fileno=source.fileno, read=read)

    monkeypatch.setattr(original_read_service, "hold_stable_file_for_read", interrupted_reader)
    with pytest.raises(AppError) as rejected:
        _read(None)
    assert rejected.value.error == "image_read_failed"
    assert not list(snapshots.iterdir())


def test_missing_temporary_storage_does_not_claim_original_is_missing(original_store, monkeypatch):
    original, _ = original_store

    def unavailable_temporary_directory(**_kwargs):
        raise FileNotFoundError("temporary storage is unavailable")

    monkeypatch.setattr(original_read_service, "TemporaryDirectory", unavailable_temporary_directory)
    with pytest.raises(AppError) as rejected:
        _read(hashlib.sha256(ORIGINAL).hexdigest())
    assert rejected.value.error == "image_read_failed"
    assert rejected.value.status_code == 503
    assert original.read_bytes() == ORIGINAL

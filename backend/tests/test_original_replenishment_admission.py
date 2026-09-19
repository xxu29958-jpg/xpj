"""Same-original admission preserves stored identity without weakening uploads."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.errors import AppError
from app.services import file_service


def _camera_jpeg(seed=7):
    pixels = bytes((index * 73 + index // 9 + seed) % 256 for index in range(37 * 29 * 3))
    image = Image.frombytes("RGB", (37, 29), pixels)
    exif = Image.Exif()
    exif[0x010F] = "PrivateCameraIdentity"
    exif[0x0112] = 6
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88, exif=exif)
    return buffer.getvalue()


@pytest.fixture
def upload_store(monkeypatch, tmp_path):
    settings = SimpleNamespace(upload_dir=tmp_path / "uploads", max_upload_size_bytes=1024 * 1024)
    monkeypatch.setattr(file_service, "get_settings", lambda: settings)
    return settings


def _ordinary_upload(data):
    return file_service.save_upload_bytes(data, tenant_id="owner", filename="camera.jpg", content_type="image/jpeg")


def _stored_bytes(saved):
    path, _ = file_service.resolve_protected_image(saved.relative_path, "owner")
    return path.read_bytes()


def test_readmitting_stored_jpeg_requires_exact_bytes_before_resanitizing(upload_store):
    original = _ordinary_upload(_camera_jpeg())
    admitted = _stored_bytes(original)
    encoded_again, _ = file_service._sanitize_image_bytes("jpg", admitted)
    assert hashlib.sha256(encoded_again).hexdigest() != original.image_hash

    replenished = file_service.save_original_replenishment_bytes(
        admitted, tenant_id="owner", expected_sha256=original.image_hash,
        filename="../../replace.jpg", content_type="image/jpeg",
    )
    assert _stored_bytes(replenished) == admitted
    assert replenished.image_hash == original.image_hash
    assert replenished.relative_path != original.relative_path
    assert "replace" not in replenished.relative_path and ".." not in replenished.relative_path
    assert _stored_bytes(original) == admitted


def test_normal_upload_still_strips_private_metadata_and_records_admitted_bytes(upload_store):
    camera = _camera_jpeg()
    saved = _ordinary_upload(camera)
    admitted = _stored_bytes(saved)
    assert admitted != camera
    assert b"PrivateCameraIdentity" not in admitted
    with Image.open(BytesIO(admitted)) as image:
        assert not image.getexif()
        assert image.size == (29, 37)
    assert saved.image_hash == hashlib.sha256(admitted).hexdigest()
    assert (saved.size_bytes, saved.media_type) == (len(admitted), "image/jpeg")
    assert saved.image_perceptual_hash is not None


def test_camera_copy_normalizes_to_the_same_admitted_original(upload_store):
    camera = _camera_jpeg()
    original = _ordinary_upload(camera)
    replenished = file_service.save_original_replenishment_bytes(
        camera, tenant_id="owner", expected_sha256=original.image_hash.upper(),
        filename="camera.jpg", content_type="image/jpeg",
    )
    assert _stored_bytes(replenished) == _stored_bytes(original)
    assert replenished.image_hash == original.image_hash
    assert replenished.size_bytes == original.size_bytes
    assert replenished.relative_path != original.relative_path


def test_different_image_is_rejected_before_any_file_write(upload_store, monkeypatch):
    original = _ordinary_upload(_camera_jpeg())
    admitted = _stored_bytes(original)
    before = set(upload_store.upload_dir.rglob("*"))
    real_open = Path.open

    def forbid_write(path, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in ("w", "a", "x", "+")), "mismatched image must never be stored"
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbid_write)
    with pytest.raises(AppError) as rejected:
        file_service.save_original_replenishment_bytes(
            _camera_jpeg(seed=29), tenant_id="owner", expected_sha256=original.image_hash,
            filename="different.jpg", content_type="image/jpeg",
        )
    assert (rejected.value.error, rejected.value.status_code) == ("image_replenishment_mismatch", 409)
    assert set(upload_store.upload_dir.rglob("*")) == before
    assert _stored_bytes(original) == admitted


def _admit(kind, data, **kwargs):
    if kind == "replenishment":
        return file_service.save_original_replenishment_bytes(
            data, tenant_id="owner", expected_sha256=hashlib.sha256(data).hexdigest(), **kwargs,
        )
    return file_service.save_upload_bytes(data, tenant_id="owner", **kwargs)


@pytest.mark.parametrize("kind", ["upload", "replenishment"])
@pytest.mark.parametrize("data", [b"", b"not an image", b"\xff\xd8\xff\xe0broken JPEG", b"\0\0\0\x1cftypheic\0\0fake"])
def test_matching_digest_never_bypasses_image_format_validation(upload_store, kind, data):
    with pytest.raises(AppError) as rejected:
        _admit(kind, data, filename="looks-valid.jpg", content_type="image/jpeg")
    assert (rejected.value.error, rejected.value.status_code) == ("unsupported_file_type", 400)
    assert not list(upload_store.upload_dir.rglob("*"))


@pytest.mark.parametrize("kind", ["upload", "replenishment"])
@pytest.mark.parametrize("limit_source", ["request", "server", "request_cannot_expand_server"])
def test_both_admissions_keep_the_existing_byte_limits(upload_store, kind, limit_source):
    data = _camera_jpeg()
    request_limit = len(data) - 1
    if limit_source != "request":
        upload_store.max_upload_size_bytes = len(data) - 1
        request_limit = None if limit_source == "server" else len(data) + 100
    with pytest.raises(AppError) as rejected:
        _admit(kind, data, max_size_bytes=request_limit)
    assert (rejected.value.error, rejected.value.status_code) == ("file_too_large", 413)
    assert not list(upload_store.upload_dir.rglob("*"))


@pytest.mark.parametrize("kind", ["upload", "replenishment"])
@pytest.mark.parametrize("cap", ["MAX_IMAGE_PIXELS", "MAX_IMAGE_DIMENSION"])
def test_both_admissions_enforce_pixel_and_dimension_caps(upload_store, monkeypatch, kind, cap):
    monkeypatch.setattr(file_service, cap, 10)
    with pytest.raises(AppError) as rejected:
        _admit(kind, _camera_jpeg())
    assert rejected.value.error == "unsupported_file_type"
    assert not list(upload_store.upload_dir.rglob("*"))


@pytest.mark.parametrize("expected", ["", "unverified", "g" * 64])
def test_replenishment_requires_a_known_valid_digest_before_storage(upload_store, expected):
    with pytest.raises(AppError) as rejected:
        file_service.save_original_replenishment_bytes(_camera_jpeg(), tenant_id="owner", expected_sha256=expected)
    assert rejected.value.error == "image_replenishment_mismatch"
    assert not list(upload_store.upload_dir.rglob("*"))


@pytest.mark.parametrize("kind", ["upload", "replenishment"])
def test_real_header_wins_over_filename_and_media_spoofing(upload_store, kind):
    buffer = BytesIO()
    Image.new("RGB", (3, 2), color=(30, 20, 10)).save(buffer, format="PNG")
    data = buffer.getvalue()
    saved = _admit(kind, data, filename="../../elsewhere.exe", content_type="text/plain")
    assert _stored_bytes(saved) == data
    assert saved.relative_path.startswith("uploads/owner/") and saved.relative_path.endswith(".png")
    assert "elsewhere" not in saved.relative_path and ".." not in saved.relative_path
    assert saved.media_type == "image/png"


def test_unique_path_collision_cannot_overwrite_or_compensate_old_original(upload_store, monkeypatch):
    monkeypatch.setattr(file_service.secrets, "token_hex", lambda _length: "one-fixed-collision")
    original = _ordinary_upload(_camera_jpeg())
    admitted = _stored_bytes(original)
    with pytest.raises(FileExistsError):
        file_service.save_original_replenishment_bytes(
            admitted, tenant_id="owner", expected_sha256=original.image_hash,
        )
    assert _stored_bytes(original) == admitted


@pytest.mark.parametrize("kind", ["upload", "replenishment"])
def test_partial_new_file_write_is_compensated_without_touching_old_original(upload_store, monkeypatch, kind):
    original = _ordinary_upload(_camera_jpeg())
    admitted = _stored_bytes(original)
    before = set(upload_store.upload_dir.rglob("*"))
    real_open = Path.open

    @contextmanager
    def interrupted_open(path, mode="r", *args, **kwargs):
        with real_open(path, mode, *args, **kwargs) as output:
            if mode != "xb":
                yield output
                return

            def write(data):
                output.write(data[:8])
                raise OSError("synthetic partial write")

            yield SimpleNamespace(write=write)

    monkeypatch.setattr(Path, "open", interrupted_open)
    with pytest.raises(OSError, match="synthetic partial write"):
        _admit(kind, admitted)
    assert set(upload_store.upload_dir.rglob("*")) == before
    assert _stored_bytes(original) == admitted

"""Actual file consumers must keep the admitted original's identity."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from app.errors import AppError
from app.models import Expense
from app.services import file_service, thumb_service
from app.services.ocr_service import _providers


def _png(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def original(monkeypatch, tmp_path):
    settings = replace(file_service.get_settings(), upload_dir=tmp_path / "uploads", generate_thumbnail=True)
    monkeypatch.setattr(file_service, "get_settings", lambda: settings)
    monkeypatch.setattr(thumb_service, "get_settings", lambda: settings)
    path = settings.upload_dir / "owner" / "receipt.png"
    path.parent.mkdir(parents=True)
    data = _png("red")
    path.write_bytes(data)
    expense = Expense(id=1, tenant_id="owner", image_path="uploads/owner/receipt.png",
        image_hash=hashlib.sha256(data).hexdigest(), image_deleted_at=None)
    return expense, path, data


def _ocr_consumer(monkeypatch, provider: str, consumed: list[bytes]):
    if provider == "local_llm":
        monkeypatch.setattr(_providers, "require_local_llm_base_url", lambda *_: None)

        def call(data, *_args):
            consumed.append(data)
            return {"raw_text": ""}

        monkeypatch.setattr(_providers, "call_local_llm_vision", call)
        return _providers.LocalLlmOcrProvider()

    def run(path):
        from pathlib import Path
        consumed.append(Path(path).read_bytes())
        return SimpleNamespace(txts=[], scores=[])

    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(RapidOCR=lambda: run))
    return _providers.RapidOcrProvider()


@pytest.mark.parametrize("provider", ["local_llm", "rapidocr"])
def test_ocr_does_not_consume_replaced_original(monkeypatch, original, provider):
    expense, path, _ = original
    path.write_bytes(_png("blue"))
    consumed = []
    ocr = _ocr_consumer(monkeypatch, provider, consumed)
    with pytest.raises(AppError) as rejected:
        ocr.extract(expense)
    assert rejected.value.error == "image_integrity_mismatch"
    assert consumed == []


@pytest.mark.parametrize("provider", ["local_llm", "rapidocr"])
@pytest.mark.parametrize("digest_known", [True, False])
def test_ocr_preserves_matching_and_legacy_original_access(monkeypatch, original, provider, digest_known):
    expense, _, data = original
    if not digest_known:
        expense.image_hash = None
    consumed = []
    _ocr_consumer(monkeypatch, provider, consumed).extract(expense)
    assert consumed == [data]
    if not digest_known:
        assert expense.image_hash is None


def test_new_thumbnail_does_not_publish_replaced_original(original):
    expense, path, _ = original
    path.write_bytes(_png("blue"))
    with pytest.raises(AppError) as rejected:
        thumb_service.stage_thumbnail(expense.image_path, tenant_id=expense.tenant_id,
            expected_sha256=expense.image_hash)
    assert rejected.value.error == "image_integrity_mismatch"
    assert not list(path.parent.glob("thumbs/*"))


@pytest.mark.parametrize("digest_known", [True, False])
def test_new_thumbnail_preserves_matching_and_legacy_original_access(original, digest_known):
    expense, path, data = original
    staged = thumb_service.stage_thumbnail(expense.image_path, tenant_id=expense.tenant_id,
        expected_sha256=expense.image_hash if digest_known else None)
    assert staged is not None
    try:
        with Image.open(staged.staging_path) as image:
            assert image.format == "JPEG"
            assert image.size == (16, 16)
        assert path.read_bytes() == data
        assert staged.source_reference == expense.image_path
        assert not staged.final_path.exists()
    finally:
        thumb_service.discard_staged_thumbnail(staged)

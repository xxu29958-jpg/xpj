"""Perceptual image duplicate detection."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

from PIL import Image

from app.database import SessionLocal
from app.models import Expense
from app.services.duplicate_service import mark_duplicate_status
from app.services.file_service import compute_image_perceptual_hash


def _png_bytes(*, changed_pixel: bool = False) -> bytes:
    image = Image.new("RGB", (32, 32), "white")
    for x in range(8, 24):
        for y in range(8, 24):
            image.putpixel((x, y), (20, 20, 20))
    if changed_pixel:
        image.putpixel((1, 1), (240, 240, 240))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_perceptual_hash_matches_tiny_visual_change() -> None:
    base = compute_image_perceptual_hash(_png_bytes())
    changed = compute_image_perceptual_hash(_png_bytes(changed_pixel=True))
    assert base is not None
    assert changed is not None
    assert (int(base, 16) ^ int(changed, 16)).bit_count() <= 5


def test_duplicate_detection_uses_perceptual_hash_for_near_images(*, identity) -> None:
    now = datetime(2026, 5, 1, tzinfo=UTC)
    base_phash = compute_image_perceptual_hash(_png_bytes())
    changed_phash = compute_image_perceptual_hash(_png_bytes(changed_pixel=True))
    assert base_phash is not None
    assert changed_phash is not None
    with SessionLocal() as db:
        original = Expense(
            tenant_id="owner",
            amount_cents=None,
            merchant=None,
            category="其他",
            source="pytest",
            image_hash="sha-base",
            image_perceptual_hash=base_phash,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        duplicate = Expense(
            tenant_id="owner",
            amount_cents=None,
            merchant=None,
            category="其他",
            source="pytest",
            image_hash="sha-changed",
            image_perceptual_hash=changed_phash,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add_all([original, duplicate])
        db.flush()

        mark_duplicate_status(db, duplicate)

        assert duplicate.duplicate_status == "suspected"
        assert duplicate.duplicate_of_id == original.id
        assert duplicate.duplicate_reason is not None
        assert "hash" in duplicate.duplicate_reason


def test_perceptual_scan_is_bounded_by_config_limit(*, identity, monkeypatch) -> None:
    """With a small scan cap, a near-duplicate older than the most-recent
    window is not swept (ENGINEERING_RULES §12 bound) and is not flagged."""
    from app.config import reset_settings_cache

    base_phash = compute_image_perceptual_hash(_png_bytes())
    changed_phash = compute_image_perceptual_hash(_png_bytes(changed_pixel=True))
    assert base_phash is not None and changed_phash is not None
    far_phash = "0" * len(base_phash)  # all-zero hash is far from a real image

    monkeypatch.setenv("DUPLICATE_PHASH_SCAN_LIMIT", "1")
    reset_settings_cache()
    try:
        with SessionLocal() as db:
            old_match = Expense(
                tenant_id="owner",
                amount_cents=None,
                merchant=None,
                category="其他",
                source="pytest",
                image_hash="sha-old",
                image_perceptual_hash=base_phash,
                status="pending",
                created_at=datetime(2026, 5, 1, tzinfo=UTC),
                updated_at=datetime(2026, 5, 1, tzinfo=UTC),
            )
            recent_filler = Expense(
                tenant_id="owner",
                amount_cents=None,
                merchant=None,
                category="其他",
                source="pytest",
                image_hash="sha-filler",
                image_perceptual_hash=far_phash,
                status="pending",
                created_at=datetime(2026, 5, 10, tzinfo=UTC),
                updated_at=datetime(2026, 5, 10, tzinfo=UTC),
            )
            db.add_all([old_match, recent_filler])
            db.flush()
            new_upload = Expense(
                tenant_id="owner",
                amount_cents=None,
                merchant=None,
                category="其他",
                source="pytest",
                image_hash="sha-new",
                image_perceptual_hash=changed_phash,
                status="pending",
                created_at=datetime(2026, 5, 20, tzinfo=UTC),
                updated_at=datetime(2026, 5, 20, tzinfo=UTC),
            )
            db.add(new_upload)
            db.flush()

            mark_duplicate_status(db, new_upload)

            # limit=1 sweeps only the most-recent candidate (the far filler);
            # the real match is older and outside the bounded window.
            assert new_upload.duplicate_status == "none"
    finally:
        reset_settings_cache()

"""Phase 6.1 — log sanitization helpers."""

from __future__ import annotations

from app.log_sanitize import mask_upload_path


def test_mask_upload_path_replaces_upload_key() -> None:
    raw = "/u/abc1234567890wxyz?tz=Asia/Shanghai"
    masked = mask_upload_path(raw)
    assert masked == "/u/***?tz=Asia/Shanghai"
    assert "abc1234567890wxyz" not in masked


def test_mask_upload_path_handles_empty() -> None:
    assert mask_upload_path("") == ""
    assert mask_upload_path(None) == ""

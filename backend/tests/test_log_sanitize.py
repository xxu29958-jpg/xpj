"""Phase 6.1 — log sanitization helpers."""

from __future__ import annotations

from app.log_sanitize import mask_token, mask_upload_path, safe_headers


def test_mask_upload_path_replaces_upload_key() -> None:
    raw = "/u/abc1234567890wxyz?tz=Asia/Shanghai"
    masked = mask_upload_path(raw)
    assert masked == "/u/***?tz=Asia/Shanghai"
    assert "abc1234567890wxyz" not in masked


def test_mask_upload_path_handles_empty() -> None:
    assert mask_upload_path("") == ""
    assert mask_upload_path(None) == ""


def test_mask_token_collapses_secret_to_stars() -> None:
    secret = "session-token-abc-xyz-1234567890"
    assert mask_token(secret) == "***"
    assert secret not in mask_token(secret)
    assert mask_token(None) == ""
    assert mask_token("") == ""


def test_safe_headers_redacts_known_secret_headers() -> None:
    raw = {
        "Authorization": "Bearer session-abc",
        "Upload-Token": "old-upload-token",
        "X-Bootstrap-Secret": "boot-secret",
        "Cookie": "session=xyz",
        "Content-Type": "application/json",
        "X-Timezone": "Asia/Shanghai",
    }
    safe = safe_headers(raw)
    assert safe["Authorization"] == "***"
    assert safe["Upload-Token"] == "***"
    assert safe["X-Bootstrap-Secret"] == "***"
    assert safe["Cookie"] == "***"
    assert safe["Content-Type"] == "application/json"
    assert safe["X-Timezone"] == "Asia/Shanghai"
    # Original mapping must not be mutated.
    assert raw["Authorization"] == "Bearer session-abc"


def test_safe_headers_masks_upload_key_in_referer_and_origin() -> None:
    # A browser following /u/<upload_key> may attach Referer/Origin with the
    # raw upload_key. Without this rule the upload_key would land in the 5xx
    # log via SanitizedLoggingMiddleware's headers=... line. The scheme + host
    # stay visible so the log line still says where the request came from.
    raw = {
        "Referer": "https://api.example.com/u/abc1234567890wxyz",
        "Origin": "https://api.example.com",
        "X-Forwarded-For": "203.0.113.7",
    }
    safe = safe_headers(raw)
    assert "abc1234567890wxyz" not in safe["Referer"]
    assert safe["Referer"] == "https://api.example.com/u/***"
    # Origin without /u/ path is unchanged.
    assert safe["Origin"] == "https://api.example.com"
    assert safe["X-Forwarded-For"] == "203.0.113.7"

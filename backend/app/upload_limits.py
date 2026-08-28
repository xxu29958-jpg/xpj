"""Shared byte limits for receipt-upload request envelopes."""

from __future__ import annotations

MULTIPART_BODY_OVERHEAD_BYTES = 1 * 1024 * 1024


def multipart_request_limit_bytes(max_file_size_bytes: int) -> int:
    """Bound a multipart body before parsers can spool any file part."""
    return max(0, int(max_file_size_bytes)) + MULTIPART_BODY_OVERHEAD_BYTES


__all__ = ["multipart_request_limit_bytes"]

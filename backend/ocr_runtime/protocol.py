"""Bounded, versioned JSON messages on an inherited private pipe."""

from __future__ import annotations

import json
from typing import BinaryIO

SCHEMA_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class OcrRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def read_message(stream: BinaryIO, limit: int) -> dict | None:
    line = stream.readline(limit + 1)
    if not line:
        return None
    if len(line) > limit or not line.endswith(b"\n"):
        raise OcrRuntimeError("ocr_protocol_invalid")
    value = json.loads(line)
    if not isinstance(value, dict) or value.get("schema") != SCHEMA_VERSION:
        raise OcrRuntimeError("ocr_protocol_invalid")
    return value


def write_message(stream: BinaryIO, value: dict, limit: int) -> None:
    encoded = json.dumps(dict(value, schema=SCHEMA_VERSION), ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(encoded) > limit:
        raise OcrRuntimeError("ocr_output_limit")
    stream.write(encoded)
    stream.flush()

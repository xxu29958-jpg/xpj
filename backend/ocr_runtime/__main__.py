"""Private child process; it receives snapshots, never ledger credentials."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ocr_runtime.protocol import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, OcrRuntimeError, read_message, write_message


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    args = parser.parse_args()
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    # The parent attaches its kill-on-close Job before granting the first request.
    engine = None
    while request := read_message(source, MAX_REQUEST_BYTES):
        if request.get("operation") == "stop":
            return 0
        response = {"request_id": request.get("request_id"), "generation": request.get("generation")}
        try:
            if request.get("operation") != "recognize":
                raise OcrRuntimeError("ocr_protocol_invalid")
            if engine is None:
                from ocr_runtime.engine import RapidEngine

                engine = RapidEngine(args.recipe, args.model_root)
            result = engine.recognize(Path(request["path"]), request["input_sha256"])
            response.update(outcome="success", result=result)
        except OcrRuntimeError as exc:
            response.update(outcome="error", error_code=exc.code)
        except ImportError:
            response.update(outcome="error", error_code="ocr_runtime_unavailable")
        except MemoryError:
            response.update(outcome="error", error_code="ocr_resource_limit")
            write_message(sink, response, MAX_RESPONSE_BYTES)
            return 1
        except Exception:
            # The parent discards private stderr, reaps this process and exposes
            # only the safe protocol error. An unexpected native/wrapper failure
            # must not leave a potentially poisoned engine alive for reuse.
            response.update(outcome="error", error_code="ocr_inference_failed")
            write_message(sink, response, MAX_RESPONSE_BYTES)
            raise
        try:
            write_message(sink, response, MAX_RESPONSE_BYTES)
        except OcrRuntimeError as exc:
            write_message(sink, {"request_id": request.get("request_id"), "generation": request.get("generation"),
                                 "outcome": "error", "error_code": exc.code}, MAX_RESPONSE_BYTES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

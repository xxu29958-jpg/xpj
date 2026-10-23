"""Private child process; it receives snapshots, never ledger credentials."""

from __future__ import annotations

import argparse
import gc
import sys
from pathlib import Path

from ocr_runtime.protocol import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, OcrRuntimeError, read_message, write_message


def _native_memory_failure(error: Exception) -> bool:
    # The pinned RapidOCR wrapper chains ONNX Runtime's C++ allocation failure;
    # it is not a Python MemoryError. Keep unrelated inference failures distinct.
    cause = error.__cause__ or error
    return (type(cause).__module__ == "onnxruntime.capi.onnxruntime_pybind11_state"
            and type(cause).__name__ == "RuntimeException" and "bad allocation" in str(cause))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    args = parser.parse_args()
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    # The parent attaches its kill-on-close Job before granting the first request.
    engine = None
    region_mode = False
    while request := read_message(source, MAX_REQUEST_BYTES):
        if request.get("operation") == "stop":
            return 0
        response = {"request_id": request.get("request_id"), "generation": request.get("generation")}
        try:
            if request.get("operation") not in {"recognize", "recognize_region"}:
                raise OcrRuntimeError("ocr_protocol_invalid")
            requested_region = request["operation"] == "recognize_region"
            if requested_region != region_mode:
                # Keep one model set inside the capacity-one worker and its Job.
                engine = None
                gc.collect()
                region_mode = requested_region
            if engine is None:
                from ocr_runtime.engine import RapidEngine

                engine = RapidEngine(args.recipe, args.model_root, region_mode=region_mode)
            if region_mode:
                result = engine.recognize_region(Path(request["path"]), request["input_sha256"], request.get("region"))
            else:
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
        except Exception as exc:
            # The parent discards private stderr, reaps this process and exposes
            # only the safe protocol error. An unexpected native/wrapper failure
            # must not leave a potentially poisoned engine alive for reuse.
            resource_failure = _native_memory_failure(exc)
            response.update(outcome="error", error_code="ocr_resource_limit" if resource_failure else "ocr_inference_failed")
            write_message(sink, response, MAX_RESPONSE_BYTES)
            if resource_failure:
                return 1
            raise
        try:
            write_message(sink, response, MAX_RESPONSE_BYTES)
        except OcrRuntimeError as exc:
            write_message(sink, {"request_id": request.get("request_id"), "generation": request.get("generation"),
                                 "outcome": "error", "error_code": exc.code}, MAX_RESPONSE_BYTES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

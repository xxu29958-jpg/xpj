"""Native allocation failures retain their resource meaning across the private pipe."""

import io
import json
from types import SimpleNamespace

import pytest

from ocr_runtime import __main__ as worker

NativeRuntimeError = type("RuntimeException", (RuntimeError,), {
    "__module__": "onnxruntime.capi.onnxruntime_pybind11_state",
})


@pytest.mark.parametrize("cause,code", [
    (NativeRuntimeError("Conv: bad allocation; private-model-path"), "ocr_resource_limit"),
    (NativeRuntimeError("Conv: invalid input shape; private-model-path"), "ocr_inference_failed"),
    (RuntimeError("bad allocation; unrelated-library"), "ocr_inference_failed"),
])
def test_native_failure_response_is_specific_and_worker_exits(monkeypatch, cause, code):
    from ocr_runtime import engine

    def fail(*_args):
        raise RuntimeError("wrapper-private-path") from cause

    monkeypatch.setattr(engine, "RapidEngine", lambda *_args: SimpleNamespace(recognize=fail))
    request = {"schema": 1, "operation": "recognize", "request_id": "call", "generation": "worker",
               "path": "synthetic-input.png", "input_sha256": "synthetic-digest"}
    source = io.BytesIO((json.dumps(request) + "\n").encode())
    sink = io.BytesIO()
    monkeypatch.setattr(worker.sys, "argv", ["worker", "--recipe", "recipe.json", "--model-root", "models"])
    monkeypatch.setattr(worker.sys, "stdin", SimpleNamespace(buffer=source))
    monkeypatch.setattr(worker.sys, "stdout", SimpleNamespace(buffer=sink))
    if code == "ocr_resource_limit":
        assert worker.main() == 1
    else:
        with pytest.raises(RuntimeError, match="wrapper-private-path"):
            worker.main()
    assert json.loads(sink.getvalue()) == {"schema": 1, "request_id": "call", "generation": "worker",
                                         "outcome": "error", "error_code": code}

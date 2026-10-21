"""Fault-injection child used only by process ownership contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

for line in sys.stdin.buffer:
    request = json.loads(line)
    if request.get("operation") == "stop":
        break
    mode = Path(request["path"]).name
    if mode.startswith("hang"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 creationflags=0x08000000 if os.name == "nt" else 0)
        Path(request["path"]).write_text(str(child.pid))
        time.sleep(60)
    if mode == "exit":
        raise SystemExit(3)
    if mode == "oversized":
        print("x" * (2 * 1024 * 1024 + 1), flush=True)
        continue
    if mode == "over-memory-limit":
        try:
            allocation = bytearray(600 * 1024 * 1024)
            del allocation
        except MemoryError:
            print(json.dumps({"schema": 1, "request_id": request["request_id"], "generation": request["generation"],
                              "outcome": "error", "error_code": "ocr_resource_limit"}), flush=True)
            raise SystemExit(1) from None
    result = {"input_sha256": request["input_sha256"], "pid": os.getpid(),
              "credential_names": [name for name in os.environ if "DATABASE" in name or "TOKEN" in name]}
    response = {"schema": 1, "request_id": request["request_id"], "generation": request["generation"],
                "outcome": "success", "result": result}
    if mode == "wrong-generation":
        response["generation"] = "previous-worker"
    print(json.dumps(response), flush=True)

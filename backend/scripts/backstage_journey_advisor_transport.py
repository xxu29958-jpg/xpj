"""Ephemeral AI wire fixture; UI/protocol evidence, explicitly not model inference."""

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


@dataclass
class AdvisorWireEvidence:
    inputs: list[dict] = field(default_factory=list)
    fail_next: bool = False
    fx_available: bool = False
    fx_requests: list[dict] = field(default_factory=list)


@contextmanager
def advisor_wire_fixture():
    state = AdvisorWireEvidence()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            length = int(self.headers["Content-Length"])
            assert 0 < length < 100_000
            body = json.loads(self.rfile.read(length))
            users = [message["content"] for message in body["messages"] if message["role"] == "user"]
            assert len(users) == 1
            inputs = json.loads(users[0])
            state.inputs.append(inputs)
            failure, state.fail_next = state.fail_next, False
            reply = {"error": {"message": "Synthetic protocol outage"}} if failure else {
                "choices": [{"message": {"content": json.dumps({
                    "summary": "合成协议样例：仅供人工核对",
                    "suggestions": [{"category": "其他", "suggested_amount_cents": 10000,
                                     "rationale": "仅用于验证建议展示，不代表模型推理。"}],
                    "confidence": 0.7}, ensure_ascii=False)}}]}
            content = json.dumps(reply, ensure_ascii=False).encode()
            self.send_response(503 if failure else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            # A bounded failure switch in front of the real dated quote provider.
            parts = urlsplit(self.path)
            assert parts.path in {"/fx/latest", "/fx/2025-01-12"}
            record = {"path": parts.path, "available": state.fx_available}
            content, status = b"temporarily unavailable for recovery verification", 503
            if state.fx_available:
                target = "https://api.frankfurter.dev/v1/" + parts.path.rsplit("/", 1)[1] + "?" + parts.query
                # Preserve the production provider's explicit client identity;
                # the upstream rejects urllib's default Python User-Agent.
                request = Request(target, headers={"User-Agent": self.headers["User-Agent"]})
                try:
                    with urlopen(request, timeout=10) as response:
                        content, status = response.read(), response.status
                except (URLError, OSError) as error:
                    record["upstream_error"] = type(error).__name__
                    record["upstream_status"] = getattr(error, "code", None)
            record["status"] = status
            state.fx_requests.append(record)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 18881), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    values = {"BUDGET_ADVISOR_PROVIDER": "openai_compat",
              "BUDGET_ADVISOR_BASE_URL": "http://127.0.0.1:18881/v1",
              "BUDGET_ADVISOR_MODEL": "synthetic-ui-protocol-fixture",
              "BUDGET_ADVISOR_API_KEY": "", "BUDGET_ADVISOR_OWNER_CONFIRMED": "false",
              "BUDGET_ADVISOR_LIVE_MIN_INTERVAL_SECONDS": "0",
              "FX_RATE_SOURCE": "frankfurter", "FX_RATE_AUTO_SYNC_ENABLED": "true",
              "FX_RATE_FRANKFURTER_URL": "http://127.0.0.1:18881/fx/latest?base=EUR"}
    original = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

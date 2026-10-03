"""Existing HTTP, file and console outputs under real isolated Uvicorn failures."""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import logging.config
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import Request

from app import errors
from app.error_reporting import retain_handled_error

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ("synthetic-token-v4", "synthetic-upload-v4", "87654321", "synthetic-password-v4")


def _configure_probe_logging(output: Path, *, drop_report: bool, broken_sink: bool):
    spec = importlib.util.spec_from_file_location("reporting_launch", ROOT / "packaging/launch.py")
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    console = io.StringIO()
    sys.stdout = console
    logging.raiseExceptions = False
    logging.config.dictConfig(launch._build_log_config(output, console=True))
    if drop_report:
        errors.report_http_error = lambda *_args, **_kwargs: None
    if broken_sink:
        class BrokenHandler(logging.Handler):
            def emit(self, _record):
                raise OSError("synthetic disk failure")
        logging.getLogger("ticketbox.http").addHandler(BrokenHandler())
    return console


def _probe_app():
    # The actual application's entire middleware/exception chain, without starting
    # its DB-dependent lifespan. Probe routes themselves have no DB dependency.
    importlib.import_module("tests._infra.env")
    from app.main import app

    @app.get("/api/unhandled-probe")
    def unhandled_probe():
        try:
            raise OSError(f"Authorization: Bearer {SECRETS[0]} C:\\private\\financial.txt")
        except OSError as exc:
            raise RuntimeError(f"https://example.test/u/{SECRETS[1]}#pairing={SECRETS[2]}") from exc

    @app.get("/api/handled-probe")
    def handled_probe():
        try:
            raise OSError(f"password={SECRETS[3]}")
        except OSError as exc:
            raise errors.AppError("server_error", status_code=503) from exc

    @app.get("/api/form-probe")
    def form_probe(request: Request):
        try:
            raise OSError("private form error")
        except OSError as exc:
            retain_handled_error(request, exc)
            return errors.HTMLResponse("original form retained", status_code=503)

    @app.get("/api/ordinary-probe")
    def ordinary_probe():
        logging.getLogger("ticketbox.ordinary").info("ordinary message without extra")
        return {"ok": True}

    @app.get("/api/refusal-probe")
    def refusal_probe():
        raise errors.AppError("permission_denied", status_code=403)
    return app


def _run_probe(output: Path, *, drop_report: bool = False, broken_sink: bool = False) -> None:
    console = _configure_probe_logging(output, drop_report=drop_report, broken_sink=broken_sink)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(_probe_app(), log_config=None, access_log=False, lifespan="off"))
    worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    worker.start()
    results = {}
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        for name in ("unhandled", "handled", "form", "ordinary", "refusal"):
            with httpx.Client(trust_env=False) as client:
                response = client.get(f"http://127.0.0.1:{listener.getsockname()[1]}/api/{name}-probe")
            results[name] = {"status": response.status_code, "request_id": response.headers.get("X-Request-Id"),
                "body": response.json() if name != "form" else response.text}
        logging.getLogger("ticketbox.thirdparty.child").warning(
            "Authorization: Bearer %s url=https://host.test/u/%s#pairing=%s password=%s", *SECRETS)
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        assert not worker.is_alive()
        logging.shutdown()
    results["file"] = (output / "backend.log").read_text(encoding="utf-8")
    results["console"] = console.getvalue()
    (output / "result.json").write_text(json.dumps(results), encoding="utf-8")


def _probe(tmp_path, mode="normal"):
    output = tmp_path / mode
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    subprocess.run([sys.executable, str(Path(__file__)), str(output), mode],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True, timeout=20)
    return json.loads((output / "result.json").read_text(encoding="utf-8"))


def _assert_request_evidence(result):
    for name, status in (("unhandled", 500), ("handled", 503), ("form", 503)):
        response = result[name]
        assert response["status"] == status
        request_id = response["request_id"]
        assert request_id and f"request_id={request_id}" in result["file"]
        if name != "form":
            assert response["body"]["request_id"] == request_id
        assert f"in {name}_probe" in result["file"]
    assert result["form"]["body"] == "original form retained"
    assert result["unhandled"]["body"]["error"] == "server_error"
    assert result["ordinary"]["body"] == {"ok": True}
    for output in (result["file"], result["console"]):
        assert "source_tree_sha256=" in output and "version=1.2.0" in output
        assert "RuntimeError" in output and "OSError" in output
        assert "backend/tests/test_error_reporting_runtime.py:" in output
        assert "ordinary message without extra" in output
        assert "Z ERROR" in output
        assert "financial.txt" not in output
        assert all(secret not in output for secret in SECRETS)
        assert "GET /api/ordinary-probe" not in output and "GET /api/refusal-probe" not in output


def test_real_http_failures_reach_existing_final_outputs_and_keep_protocol(tmp_path):
    _assert_request_evidence(_probe(tmp_path))


def test_removing_unhandled_report_breaks_the_same_request_evidence(tmp_path):
    with pytest.raises(AssertionError):
        _assert_request_evidence(_probe(tmp_path, "drop-report"))


def test_logging_sink_failure_does_not_replace_http_outcomes(tmp_path):
    result = _probe(tmp_path, "broken-sink")
    for name, status in (("unhandled", 500), ("handled", 503), ("form", 503), ("ordinary", 200), ("refusal", 403)):
        response = result[name]
        assert response["status"] == status
        if name in {"unhandled", "handled", "refusal"}:
            assert response["body"]["request_id"] == response["request_id"]
    assert result["form"]["body"] == "original form retained"
    assert result["ordinary"]["body"] == {"ok": True}


def _run_rotation_probe(output: Path):
    _configure_probe_logging(output, drop_report=False, broken_sink=False)
    handler = next(item for item in logging.getLogger().handlers if hasattr(item, "maxBytes"))
    assert (handler.maxBytes, handler.backupCount) == (5_000_000, 3)
    handler.maxBytes = 1024  # Exercise the existing rotator without producing 20 MB in every test.
    logger = logging.getLogger("ticketbox.rotation.child")
    for index in range(35):
        logger.warning("ordinary rotation event=%s token=synthetic-rotation-secret", index)
    logging.shutdown()
    files = {path.name: path.read_text(encoding="utf-8") for path in output.glob("backend.log*")}
    (output / "result.json").write_text(json.dumps(files), encoding="utf-8")


def test_rotated_files_keep_build_identity_and_final_sanitization(tmp_path):
    files = _probe(tmp_path, "rotation")
    assert set(files) == {"backend.log", "backend.log.1", "backend.log.2", "backend.log.3"}
    for text in files.values():
        assert "source_tree_sha256=" in text and "version=1.2.0" in text
        assert "synthetic-rotation-secret" not in text
        assert "ordinary rotation event=" in text


def test_frozen_reports_use_existing_manifest_identity_without_claiming_a_git_sha(tmp_path, monkeypatch):
    from app.diagnostic_identity import diagnostic_build_identity

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "backend.exe"))
    manifest = {"artifact_type": "ticketbox-frozen-backend", "source": {"fingerprint": "a" * 64},
        "payload": {"fingerprint": "b" * 64}}
    (tmp_path / "BUILD_PROVENANCE.json").write_text(json.dumps(manifest), encoding="utf-8")
    identity = diagnostic_build_identity()
    assert f"recorded_source_sha256={'a' * 64}" in identity
    assert f"recorded_payload_sha256={'b' * 64}" in identity
    assert "git" not in identity.lower()


if __name__ == "__main__":
    if sys.argv[2] == "rotation":
        _run_rotation_probe(Path(sys.argv[1]))
    else:
        _run_probe(Path(sys.argv[1]), drop_report=sys.argv[2] == "drop-report", broken_sink=sys.argv[2] == "broken-sink")

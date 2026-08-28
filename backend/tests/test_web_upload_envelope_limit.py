from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace

from _web_public_session_support import PUBLIC_HOST, mint_session, public_client
from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_auth import SESSION_COOKIE_NAME

_CHUNK_SIZE = 64 * 1024


def _multipart_chunks(csrf_token: str, boundary: str) -> list[bytes]:
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="csrf_token"\r\n\r\n'
        f"{csrf_token}\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="large.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode()
    body = prefix + (b"x" * (2 * 1024 * 1024)) + f"\r\n--{boundary}--\r\n".encode()
    return [body[offset : offset + _CHUNK_SIZE] for offset in range(0, len(body), _CHUNK_SIZE)]


def _public_upload_scope(
    *,
    token: str,
    csrf_token: str,
    csrf_seed: str,
    boundary: str,
) -> dict[str, object]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/web/pending/upload",
        "raw_path": b"/web/pending/upload",
        "query_string": b"ledger_id=owner",
        "root_path": "",
        "headers": [
            (b"host", PUBLIC_HOST.encode()),
            (b"origin", f"https://{PUBLIC_HOST}".encode()),
            (b"x-csrf-token", csrf_token.encode()),
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"transfer-encoding", b"chunked"),
            (
                b"cookie",
                f"{SESSION_COOKIE_NAME}={token}; xpj_csrf_seed={csrf_seed}".encode(),
            ),
        ],
        "client": ("203.0.113.10", 50002),
        "server": (PUBLIC_HOST, 443),
    }


async def _run_chunked_request(
    scope: dict[str, object],
    chunks: list[bytes],
) -> tuple[list[dict], int]:
    sent: list[dict] = []
    next_chunk = 0
    yielded_bytes = 0

    async def receive():
        nonlocal next_chunk, yielded_bytes
        if next_chunk >= len(chunks):
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = chunks[next_chunk]
        next_chunk += 1
        yielded_bytes += len(chunk)
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": next_chunk < len(chunks),
        }

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent, yielded_bytes


def test_public_pending_upload_caps_chunked_multipart_before_framework_parse(
    client: TestClient,
    monkeypatch,
    *,
    identity,
) -> None:
    from app.routes import _upload_request as upload_request_routes
    from app.services import file_service

    token = mint_session(client, identity=identity)
    pub = public_client()
    pub.cookies.set(SESSION_COOKIE_NAME, token, domain=PUBLIC_HOST, path="/")
    page = pub.get("/web/pending")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and csrf is not None, page.text

    small_settings = replace(file_service.get_settings(), max_upload_size_mb=0)
    monkeypatch.setattr(file_service, "get_settings", lambda: small_settings)
    monkeypatch.setattr(upload_request_routes, "get_settings", lambda: small_settings)

    boundary = "ticketbox-chunked-limit"
    csrf_seed = pub.cookies.get("xpj_csrf_seed")
    assert csrf_seed
    scope = _public_upload_scope(
        token=token,
        csrf_token=csrf.group(1),
        csrf_seed=csrf_seed,
        boundary=boundary,
    )
    sent, yielded_bytes = asyncio.run(
        _run_chunked_request(scope, _multipart_chunks(csrf.group(1), boundary))
    )

    start = next(message for message in sent if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    assert start["status"] == 413, response_body
    assert json.loads(response_body)["error"] == "file_too_large"
    assert yielded_bytes <= (1024 * 1024) + _CHUNK_SIZE

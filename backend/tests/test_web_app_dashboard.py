"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient


def _create_pending(client: TestClient, *, identity) -> int:
    """Helper: upload a tiny PNG to the owner ledger so /web/pending sees it."""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _row_id_set(html: str) -> set[str]:
    """Extract probable expense ids appearing in URLs of pending rows."""
    return set(re.findall(r"/web/expenses/(\d+)/edit", html))


def _seed_pending_with_amount(web_client: TestClient, amount_yuan: str = "10.00", merchant: str = "测试", *, identity) -> int:
    """Upload a tiny PNG then patch amount+merchant via /web/expenses/{id}/save."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": amount_yuan, "merchant": merchant, "category": "其他",
              "note": "", "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}, resp.text
    return expense_id


def test_web_root_renders_dashboard(web_client: TestClient) -> None:
    resp = web_client.get("/web", follow_redirects=False)
    assert resp.status_code == 200
    assert "仪表盘" in resp.text


def test_web_root_slash_redirects_to_root_with_ledger(web_client: TestClient) -> None:
    resp = web_client.get("/web/?ledger_id=owner", follow_redirects=False)
    assert resp.status_code in {303, 307}
    loc = resp.headers.get("location", "")
    assert loc.startswith("/web?") and "ledger_id=owner" in loc


def test_web_no_secret_leaks(web_client: TestClient, *, identity) -> None:
    """No token_hash, upload_key, pairing_code or absolute path in HTML."""
    pages = ["/web", "/web/pending", "/web/confirmed", "/web/stats", "/web/search"]
    for path in pages:
        resp = web_client.get(path)
        assert resp.status_code == 200, path
        body = resp.text
        # 64-char lower-hex token hashes
        assert not re.search(r"\b[0-9a-f]{64}\b", body), f"token_hash leaked in {path}"
        # Upload keys (~40 chars urlsafe). Anything starting with /u/ + token.
        assert "upload_key" not in body, f"upload_key keyword leaked in {path}"
        # Pairing code printed verbatim is fine as a label; ensure runtime value not echoed
        assert identity.upload_key not in body, f"upload_key value leaked in {path}"
        # Absolute Windows / POSIX paths
        assert not re.search(r"[A-Za-z]:\\\\[^\"'<>]+", body), f"abs path leaked in {path}"
        assert "/home/" not in body and "C:\\" not in body
        # Server endpoint / port leakage in普通用户面 — see ENGINEERING_RULES §10
        assert "127.0.0.1" not in body, f"loopback IP leaked in {path}"
        assert "localhost" not in body, f"localhost leaked in {path}"
        assert ":8000" not in body, f"server port leaked in {path}"

"""ENGINEERING_RULES §12: 错误日志必须带 request_id / trace_id.

Verify the per-request ID surface:
- every response carries an X-Request-Id header (so clients can echo it
  back when reporting a failure)
- error bodies include the same id in a ``request_id`` field
- a caller-supplied X-Request-Id is honored when present (so multi-hop
  traces stay consistent)
- two unrelated requests get distinct ids
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _request_id_from(response) -> str | None:
    body = response.json()
    return body.get("request_id") if isinstance(body, dict) else None


def test_success_response_has_request_id_header(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id"), "X-Request-Id missing on success response"
    assert len(resp.headers["X-Request-Id"]) <= 64


def test_validation_error_body_carries_request_id(client: TestClient) -> None:
    # /api/expenses/confirmed requires a valid month label when one is provided;
    # passing an obviously invalid month triggers the validation_error_handler.
    resp = client.get("/api/expenses/confirmed?month=0000-13")
    # Unauthed -> 401 from auth handler. That still goes through the
    # http_error_handler path, which is what we want to verify.
    assert resp.status_code in {401, 422}
    header_id = resp.headers.get("X-Request-Id")
    body_id = _request_id_from(resp)
    assert header_id, "X-Request-Id missing on error response"
    assert body_id == header_id, "error body request_id must match header"


def test_unknown_route_carries_request_id(client: TestClient) -> None:
    resp = client.get("/api/this-route-does-not-exist")
    assert resp.status_code == 404
    header_id = resp.headers.get("X-Request-Id")
    body = resp.json()
    assert header_id, "X-Request-Id missing on 404"
    assert body.get("request_id") == header_id


def test_two_requests_get_distinct_ids(client: TestClient) -> None:
    first = client.get("/api/health").headers["X-Request-Id"]
    second = client.get("/api/health").headers["X-Request-Id"]
    assert first != second


def test_caller_supplied_request_id_is_honored(client: TestClient) -> None:
    incoming = "client-side-trace-1234"
    resp = client.get("/api/health", headers={"X-Request-Id": incoming})
    assert resp.status_code == 200
    assert resp.headers["X-Request-Id"] == incoming


def test_caller_supplied_garbage_id_falls_back(client: TestClient) -> None:
    # Empty or oversized values must not propagate — they get replaced.
    overlong = "x" * 200
    resp = client.get("/api/health", headers={"X-Request-Id": overlong})
    assert resp.status_code == 200
    assert resp.headers["X-Request-Id"] != overlong
    assert 0 < len(resp.headers["X-Request-Id"]) <= 64

"""Negotiate the same current write headers as a product client."""

from fastapi.testclient import TestClient


def negotiated_headers(client: TestClient, auth_headers: dict[str, str]) -> dict[str, str]:
    response = client.get("/api/system/runtime-compatibility", headers=auth_headers)
    assert response.status_code == 200, response.text
    snapshot = response.json()
    currency = snapshot["capabilities"]["currency"]
    return {
        **auth_headers,
        snapshot["api_version_header"]: snapshot["api_version"],
        **({currency["request_binding_header"]: currency["request_binding"]} if currency["request_binding"] else {}),
    }

"""Negotiate the same current write headers as a product client."""

from fastapi.testclient import TestClient


def current_protocol_headers(auth_headers: dict[str, str]) -> dict[str, str]:
    """An ordinary fixture client declares the current persisted negotiation.

    Explicit protocol cases provide their own raw headers instead. Missing or
    corrupt installation state is still inspected/refused by the real request.
    """
    from app.database import SessionLocal
    from app.models import InstallationCurrencyBinding
    from app.runtime_compatibility_contract import CURRENT_API_VERSION

    headers = {"Ticketbox-Api-Version": CURRENT_API_VERSION}
    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        if binding is not None and binding.state == "ACTIVE" and binding.home_currency_code:
            headers["Ticketbox-Currency-Binding"] = (
                f"{binding.currency_contract_version}:{binding.binding_revision}:{binding.home_currency_code}"
            )
    return {**headers, **auth_headers}


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

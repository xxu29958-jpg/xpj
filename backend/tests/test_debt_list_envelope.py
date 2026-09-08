"""Envelope-level installation currency capability on ``GET /api/debts`` (PR#255 R6/R8-3).

Split from ``test_debts.py`` to keep both files inside the codebase-audit 500-LOC budget.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from tests._infra.currency import activate_test_currency_authority


def _idem_headers(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


@pytest.mark.currency_binding_unbound
def test_list_debts_envelope_carries_installation_home_currency(client: TestClient, *, identity) -> None:
    # Unchosen setup cannot offer CNY. Explicit confirmation supplies the list
    # envelope even before the first debt, and the record keeps that meaning.
    empty_list = client.get("/api/debts", headers=identity.app_headers)
    assert empty_list.status_code == 200, empty_list.json()
    assert empty_list.json()["items"] == []
    assert empty_list.json()["home_currency_code"] is None
    with SessionLocal() as db:
        activate_test_currency_authority(db, "CNY")
        db.commit()
    chosen_list = client.get("/api/debts", headers=identity.app_headers)
    assert chosen_list.status_code == 200
    assert chosen_list.json()["items"] == []
    assert chosen_list.json()["home_currency_code"] == "CNY"

    created = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "房东",
            "principal_amount_cents": 30000,
        },
    )
    assert created.status_code == 201, created.json()

    listing = client.get("/api/debts", headers=identity.app_headers)
    assert listing.status_code == 200, listing.json()
    assert listing.json()["home_currency_code"] == "CNY"
    assert listing.json()["items"][0]["home_currency_code"] == "CNY"


def test_list_debts_envelope_keeps_persisted_authority_on_misconfigured_env(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # C02 retires the PR#255 env bridge: runtime configuration drift must not
    # erase or reinterpret the persisted installation authority on a read.
    # An obsolete environment value cannot replace that authority.
    created = client.post(
        "/api/debts",
        headers=_idem_headers(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "房东",
            "principal_amount_cents": 30000,
        },
    )
    assert created.status_code == 201, created.json()

    # 伪造码选 "ZZZ"：marker 审计词表（见 _audit_codebase.audit_todos）不含它。
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "ZZZ")
    get_settings.cache_clear()
    try:
        listing = client.get("/api/debts", headers=identity.app_headers)
        assert listing.status_code == 200, listing.json()
        assert listing.json()["home_currency_code"] == "CNY"
        assert len(listing.json()["items"]) == 1
        assert listing.json()["items"][0]["home_currency_code"] == "CNY"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()

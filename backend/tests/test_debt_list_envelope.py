"""Envelope-level installation currency capability on ``GET /api/debts`` (PR#255 R6/R8-3).

Split from ``test_debts.py`` to keep both files inside the codebase-audit 500-LOC budget.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings


def _idem_headers(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


def test_list_debts_envelope_carries_installation_home_currency(client: TestClient, *, identity) -> None:
    # ADR-0061 C02/C03 / PR#255 R6: the list envelope repeats the installation-level
    # currency capability (the same binding the write path stamps per record) so an
    # EMPTY ledger's clients can resolve the ledger currency for first-record
    # creation — record-level-only delivery made "wait for the first record" circular.
    # Empty and non-empty lists both carry it, matching the record-level stamp.
    empty_list = client.get("/api/debts", headers=identity.app_headers)
    assert empty_list.status_code == 200, empty_list.json()
    assert empty_list.json()["items"] == []
    assert empty_list.json()["home_currency_code"] == "CNY"

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


def test_list_debts_envelope_degrades_to_null_on_misconfigured_env(
    client: TestClient, monkeypatch, *, identity
) -> None:
    # PR#255 R8-3：env 配错时读路径 best-effort 降级 —— 列表仍 200、信封
    # home_currency_code 落 null（客户端对 null capability fail closed），历史 record
    # 读不受影响；写路径盖章维持 fail-fast（不在本钉范围）。
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
        assert listing.json()["home_currency_code"] is None
        assert len(listing.json()["items"]) == 1
        assert listing.json()["items"][0]["home_currency_code"] == "CNY"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()

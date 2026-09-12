"""Real financial commands and both CSV downloads retain frozen offset evidence."""

import csv
from io import StringIO
from uuid import uuid4

import pytest

from app.main import app
from app.routes.web_app import _require_local
from tests._runtime_protocol import negotiated_headers
from tests.expense_correction_support import idem


def _rate(client, identity, day, value, *, expected_row_version=0):
    response = client.put(
        f"/api/exchange-rates/USD/{day}",
        headers=idem(negotiated_headers(client, identity.app_headers)),
        json={
            "currency_code": "USD", "home_currency_code": "CNY", "rate_date": day,
            "rate_to_cny": value, "source": "manual", "expected_row_version": expected_row_version,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_offset(client, identity, kind):
    response = client.post(
        "/api/expenses/manual", headers=identity.app_headers,
        json={
            "client_ref": str(uuid4()), "original_currency_code": "USD", "original_amount_minor": 10000,
            "expense_time": "2026-05-04T08:00:00Z", "merchant": f"Frozen {kind}",
            "category": "购物", "tags": "旅行",
        },
    )
    assert response.status_code == 200, response.text
    root = response.json()
    assert root["status"] == "confirmed"
    body = {
        "kind": kind, "accounting_date": "2026-05-05", "reason": "Export frozen evidence",
        "expected_row_version": root["row_version"],
    }
    if kind != "reversal":
        body["original_amount_minor"] = 2500
    response = client.post(
        f"/api/expenses/{root['id']}/offsets", headers=idem(identity.app_headers), json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _download(client, path, headers, params):
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.DictReader(StringIO(response.text.lstrip("\ufeff"))))


@pytest.mark.real_db
def test_api_and_web_export_original_offset_fx_after_shared_quotes_change(client, identity, monkeypatch):
    # Only loopback admission is supplied by the test host; ledger/auth resolution stays real.
    monkeypatch.setitem(app.dependency_overrides, _require_local, lambda: None)
    original_rate = _rate(client, identity, "2026-05-04", "7")
    refund_rate = _rate(client, identity, "2026-05-05", "8")
    bundles = [_create_offset(client, identity, kind) for kind in ("refund", "chargeback", "reversal")]
    _rate(client, identity, "2026-05-04", "9", expected_row_version=original_rate["row_version"])
    _rate(client, identity, "2026-05-05", "10", expected_row_version=refund_rate["row_version"])
    filters = {"month": "2026-05", "category": "购物", "tag": "旅行", "timezone": "Asia/Shanghai"}

    api_rows = _download(client, "/api/expenses/export.csv", identity.app_headers, filters)
    web_rows = _download(client, "/web/export.csv", {}, {**filters, "ledger_id": "owner"})

    assert api_rows == web_rows
    assert len(api_rows) == 6
    listed = client.get("/api/expenses/confirmed", headers=identity.app_headers, params=filters)
    assert listed.status_code == 200, listed.text
    offset_projections = {
        item["offset"]["public_id"]: item["offset"]
        for item in listed.json()["items"] if item["entry_kind"] == "offset"
    }
    by_public_id = {row["public_id"]: row for row in api_rows}
    for bundle in bundles:
        root = bundle["root"]
        offset, = bundle["active_offsets"]
        reversal = offset["kind"] == "reversal"
        row = by_public_id[offset["public_id"]]
        assert row["entry_kind"] == "offset"
        assert row["offset_kind"] == offset["kind"]
        assert row["root_expense_public_id"] == root["public_id"]
        assert row["original_currency_code"] == "USD"
        assert row["home_currency_code"] == "CNY"
        assert row["original_amount_minor"] == str(offset["original_amount_minor"])
        assert row["amount_cents"] == str(offset["amount_cents"])
        assert row["stream_amount_cents"] == ("0" if reversal else "-20000")
        assert row["exchange_rate_to_cny"] == offset["exchange_rate_to_cny"] == (
            "7.00000000" if reversal else "8.00000000"
        )
        assert row["exchange_rate_date"] == offset["exchange_rate_date"] == (
            "2026-05-04" if reversal else "2026-05-05"
        )
        assert row["exchange_rate_source"] == offset["exchange_rate_source"] == "manual"
        for field in ("exchange_rate_to_cny", "exchange_rate_date", "exchange_rate_source"):
            assert offset_projections[offset["public_id"]][field] == offset[field]
        root_row = by_public_id[root["public_id"]]
        assert root_row["exchange_rate_to_cny"] == "7.00000000"
        assert root_row["exchange_rate_date"] == "2026-05-04"
        reread = client.get(f"/api/expenses/{root['id']}/fact-bundle", headers=identity.app_headers)
        assert reread.status_code == 200, reread.text
        assert reread.json() == bundle

    # Neither download may leak the original ledger through a requested filter.
    assert _download(client, "/api/expenses/export.csv", identity.gray_app_headers, filters) == []
    assert _download(client, "/web/export.csv", {}, {**filters, "ledger_id": "tester_1"}) == []

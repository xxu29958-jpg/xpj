"""The native rate command consumes its own OCC, preserving the original command."""

import importlib
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.routes import _web_rate_recovery as web


def test_native_rate_form_uses_rate_occ_without_borrowing_original_command_occ(monkeypatch):
    app = FastAPI()
    writer = Mock(return_value=SimpleNamespace(currency_code="USD", home_currency_code="JPY",
        rate_date=date(2026, 5, 4), rate_to_cny="150", row_version=4))
    monkeypatch.setattr(web, "set_exchange_rate_idempotently", writer)
    monkeypatch.setattr(web, "resolve_web_actor_account_id", lambda *_: 7)

    @app.post("/rate")
    def rate(original: dict[str, str] = Depends(web.rate_recovery_form)):
        values = {key: original.get(f"fx_{key}", "") for key in web._RATE_FIELDS}
        result = web.submit_recovery_rate(Mock(), object(), "original", values)
        return {"original": original, "status_code": result["status_code"]}

    original = {"expected_row_version": "9", "idempotency_key": "original-command",
        "amount_major": "12.50", "fx_currency_code": "USD", "fx_home_currency_code": "JPY",
        "fx_rate_date": "2026-05-04", "fx_rate_to_cny": "150", "fx_idempotency_key": "rate-command"}
    with TestClient(app) as client:
        missing = client.post("/rate", data=original).json()
        assert missing["status_code"] == 409
        assert missing["original"]["expected_row_version"] == "9"
        writer.assert_not_called()
        accepted = client.post("/rate", data={**original, "fx_expected_row_version": "3"}).json()
    assert accepted["status_code"] == 200
    assert all(accepted["original"][key] == value for key, value in original.items())
    assert writer.call_args.kwargs["payload"].expected_row_version == 3
    assert writer.call_args.kwargs["idempotency_key"] == "rate-command"


def test_live_rate_routes_declare_their_consumed_rate_token():
    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    audit = importlib.import_module("_audit_mutate_token_coverage")
    schema = audit._load_openapi_app_schema()
    for path in ("/web/debts/rate", "/web/expenses/{expense_id}/offset-rate"):
        operation = schema["paths"][path]["post"]
        body = operation["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]
        resolved = audit._resolve_ref(schema, body["$ref"])
        assert resolved["properties"]["fx_expected_row_version"]["type"] == "string"
        assert audit._operation_carries_token(schema, operation)
        without_rate = {**resolved, "properties": {
            key: value for key, value in resolved["properties"].items() if key != "fx_expected_row_version"
        }}
        assert not audit._schema_carries_token(schema, without_rate)

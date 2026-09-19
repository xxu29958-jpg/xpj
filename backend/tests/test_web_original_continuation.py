"""Web adapters preserve the captured attachment intent before binary admission."""

import json
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.errors import AppError
from app.routes import web_inbox_capture, web_originals
from app.routes.web_common import _require_local

SCOPE = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account",
         "ledgerId": "owner", "deviceId": "device"}
AUTH = SimpleNamespace(ledger_id="owner", account_id=7, device_id=11, role="owner")


def _app(module, monkeypatch, session_auth=AUTH):
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: Mock()
    app.dependency_overrides[_require_local] = lambda: None

    @app.middleware("http")
    async def session(request, call_next):
        request.state.web_session_auth = session_auth
        return await call_next(request)

    @app.exception_handler(AppError)
    async def error(_request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": exc.error}, status_code=exc.status_code)

    monkeypatch.setattr(module, "_list_ledger_options", lambda _db: [])
    monkeypatch.setattr(module, "_resolve_selected_ledger_id", lambda *_a, **_k: "owner")
    monkeypatch.setattr(module, "_require_selected_ledger_write", lambda *_a: None)
    return app


def test_native_upload_passes_original_key_and_actor_to_existing_upload_owner(monkeypatch):
    app = _app(web_inbox_capture, monkeypatch)
    monkeypatch.setattr(web_inbox_capture, "resolve_web_actor", lambda *_a: (7, 11))
    # The shared scope reader remains the real adapter boundary; no alternate scope is minted.
    monkeypatch.setattr("app.services.manual_expense_draft_presenter.manual_draft_scope", lambda *_a: SCOPE)
    owner = AsyncMock(return_value=SimpleNamespace(enrichment_task_public_id="task", model_dump=lambda **_: {}))
    monkeypatch.setattr(web_inbox_capture, "handle_upload", owner)
    with TestClient(app) as client:
        response = client.post("/web/pending/upload", params={"ledger_id": "owner", "timezone": "UTC",
            "idempotency_key": "a" * 32, "draft_scope": json.dumps(SCOPE)},
            files={"file": ("receipt.png", b"captured bytes", "image/png")}, follow_redirects=False)
    assert response.status_code == 303
    assert owner.call_args.kwargs["idempotency_key"] == "a" * 32
    assert owner.call_args.kwargs["timezone_name"] == "UTC"
    assert owner.call_args.kwargs["initiator_device_id"] == 11


def test_device_free_upload_keeps_native_redirect_without_claiming_a_bound_ack(monkeypatch):
    app = _app(web_inbox_capture, monkeypatch, session_auth=None)
    monkeypatch.setattr(web_inbox_capture, "resolve_web_actor", lambda *_a: (None, None))
    owner = AsyncMock(return_value=SimpleNamespace(enrichment_task_public_id="task", model_dump=lambda **_: {}))
    monkeypatch.setattr(web_inbox_capture, "handle_upload", owner)
    with TestClient(app) as client:
        response = client.post("/web/pending/upload", params={"ledger_id": "owner", "idempotency_key": "a" * 32},
            files={"file": ("receipt.png", b"captured bytes", "image/png")},
            headers={"Accept": "application/json"}, follow_redirects=False)
    assert response.status_code == 303
    assert owner.call_args.kwargs["idempotency_key"] == "a" * 32
    assert owner.call_args.kwargs["initiator_device_id"] is None


@pytest.mark.parametrize("changed", ["datasetId", "clientGeneration", "accountId", "ledgerId", "deviceId"])
def test_native_upload_refuses_changed_binding_before_reading_or_writing_file(monkeypatch, changed):
    app = _app(web_inbox_capture, monkeypatch)
    monkeypatch.setattr("app.services.manual_expense_draft_presenter.manual_draft_scope", lambda *_a: SCOPE)
    owner = AsyncMock(side_effect=AssertionError("must not admit bytes for another binding"))
    monkeypatch.setattr(web_inbox_capture, "handle_upload", owner)
    captured = {**SCOPE, changed: "old-value"}
    with TestClient(app) as client:
        response = client.post("/web/pending/upload", params={"ledger_id": "owner", "idempotency_key": "a" * 32,
            "draft_scope": json.dumps(captured)}, content=b"invalid multipart", follow_redirects=False)
    assert response.status_code == 409
    owner.assert_not_called()


def _command_query():
    return {"ledger_id": "owner", "draft_scope": json.dumps(SCOPE), "idempotency_key": "a" * 32,
            "expected_row_version": "7", "expected_sha256": "c" * 64}


@pytest.mark.parametrize("operation,owner_name,fields", [
    ("verify", "verify_original", {"reviewed_sha256": "b" * 64}),
    ("cleanup/retry", "continue_original_cleanup", {"request_id": "12345678-1234-1234-1234-123456789012"}),
    ("cleanup/cancel", "continue_original_cleanup", {"request_id": "12345678-1234-1234-1234-123456789012"}),
])
def test_web_original_forms_deliver_original_version_key_actor_and_body(monkeypatch, operation, owner_name, fields) -> None:
    from app.schemas._original_attachment import OriginalCommandReceipt
    from app.services.time_service import now_utc
    app = _app(web_originals, monkeypatch)
    monkeypatch.setattr("app.services.manual_expense_draft_presenter.manual_draft_scope", lambda *_a: SCOPE)
    receipt = OriginalCommandReceipt(operation="verify_original", expense_id=17, public_id="bill", row_version=8,
        sha256="b" * 64, accepted_at=now_utc())
    owner = Mock(return_value=receipt)
    monkeypatch.setattr(web_originals, owner_name, owner)
    with TestClient(app) as client:
        response = client.post(f"/web/expenses/17/original/{operation}", params=_command_query(), data=fields,
                               headers={"Accept": "application/json"})
    assert response.status_code == 200, response.text
    assert response.json()["ack"] == {"scope": SCOPE, "clientRef": "a" * 32}
    assert response.json()["receipt"] == receipt.model_dump(mode="json")
    assert response.json()["next"].startswith("/web/expenses/17/original?")
    args = owner.call_args.kwargs
    assert args["auth"] is AUTH and args["expense_id"] == 17
    assert args["idempotency_key"] == "a" * 32 and args["payload"].expected_row_version == 7
    for name, value in fields.items():
        assert str(getattr(args["payload"], name)) == value
    if operation.startswith("cleanup/"):
        assert args["cancel_remaining"] is (operation == "cleanup/cancel")


def test_replenishment_passes_exact_file_to_owner_and_refuses_changed_scope_before_parser(monkeypatch):
    from app.schemas._original_attachment import OriginalCommandReceipt
    from app.services.time_service import now_utc
    app = _app(web_originals, monkeypatch)
    monkeypatch.setattr("app.services.manual_expense_draft_presenter.manual_draft_scope", lambda *_a: SCOPE)
    receipt = OriginalCommandReceipt(operation="replenish_original", expense_id=17, public_id="bill", row_version=8,
        sha256="c" * 64, accepted_at=now_utc())
    owner = Mock(return_value=receipt)
    monkeypatch.setattr(web_originals, "replenish_original", owner)
    with TestClient(app) as client:
        response = client.post("/web/expenses/17/original/replenish", params=_command_query(),
            files={"file": ("admitted-original.jpg", b"exact admitted bytes", "image/jpeg")},
            headers={"Accept": "application/json"})
        assert response.status_code == 200, response.text
        args = owner.call_args.kwargs
        assert args["data"] == b"exact admitted bytes" and args["filename"] == "admitted-original.jpg"
        assert args["content_type"] == "image/jpeg" and args["payload"].expected_sha256 == "c" * 64
        query = {**_command_query(), "draft_scope": json.dumps({**SCOPE, "deviceId": "other"})}
        refused = client.post("/web/expenses/17/original/replenish", params=query, content=b"not multipart")
        assert refused.status_code == 409
        assert owner.call_count == 1


def test_original_page_does_not_adopt_health_digest_as_user_review(monkeypatch) -> None:
    from datetime import datetime
    from pathlib import Path

    from fastapi.templating import Jinja2Templates
    from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

    from app.schemas._original_attachment import OriginalHealthResponse
    app = _app(web_originals, monkeypatch)
    monkeypatch.setattr("app.services.manual_expense_draft_presenter.manual_draft_scope", lambda *_a: SCOPE)
    templates = Jinja2Templates(directory=Path(__file__).parents[1] / "app/templates/web")
    templates.env.loader = ChoiceLoader([DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app/templates/web")])
    monkeypatch.setattr(web_originals, "templates", templates)
    monkeypatch.setattr(web_originals, "_base_ctx", lambda request, **_: {"request": request, "can_write": True,
                                                                      "selected_ledger_id": "owner"})
    monkeypatch.setattr(web_originals, "get_expense", lambda *_a: SimpleNamespace(merchant="original merchant"))
    monkeypatch.setattr(web_originals, "inspect_expense_original", lambda *_a, **_k: OriginalHealthResponse(
        expense_id=17, public_id="bill", row_version=7, state="unverified", observed_sha256="d" * 64,
        checked_at=datetime.now(UTC)))
    with TestClient(app) as client:
        response = client.get("/web/expenses/17/original?ledger_id=owner")
    assert response.status_code == 200
    assert 'name="reviewed_sha256" value=""' in response.text
    assert "d" * 64 not in response.text
    assert "打开实际原图" in response.text and "data-original-reviewed disabled required" in response.text


def test_original_commands_require_real_browser_identity_before_file_admission(monkeypatch):
    app = _app(web_originals, monkeypatch, session_auth=None)
    parser = AsyncMock(side_effect=AssertionError("identity must precede binary parsing"))
    monkeypatch.setattr(web_originals, "read_request_upload", parser)
    with TestClient(app) as client:
        query = _command_query()
        assert client.post("/web/expenses/17/original/verify", params=query,
            data={"reviewed_sha256": "b" * 64}).status_code == 401
        assert client.post("/web/expenses/17/original/replenish", params=query, content=b"unknown").status_code == 401
        body = {"request_id": "12345678-1234-1234-1234-123456789012"}
        assert client.post("/web/expenses/17/original/cleanup/retry", params=query, data=body).status_code == 401
        assert client.post("/web/expenses/17/original/cleanup/cancel", params=query, data=body).status_code == 401
    parser.assert_not_called()


def test_original_viewer_is_denied_before_replenishment_parser(monkeypatch):
    app = _app(web_originals, monkeypatch)
    def deny(*_a):
        raise AppError("permission_denied", status_code=403)
    monkeypatch.setattr(web_originals, "_require_selected_ledger_write", deny)
    parser = AsyncMock(side_effect=AssertionError("viewer must not parse original upload"))
    monkeypatch.setattr(web_originals, "read_request_upload", parser)
    with TestClient(app) as client:
        response = client.post("/web/expenses/17/original/replenish", params=_command_query(), content=b"unknown")
    assert response.status_code == 403
    parser.assert_not_called()


@pytest.mark.parametrize("row_count,next_after", [(25, None), (26, 75)])
def test_original_reference_query_preserves_ledger_cursor_and_bounded_page(row_count, next_after):
    from sqlalchemy.dialects import postgresql

    from app.services.expense_query import list_original_inspection_expenses

    rows = [SimpleNamespace(id=value) for value in range(51, 51 + row_count)]
    db = Mock()
    db.scalars.return_value = rows
    page, cursor = list_original_inspection_expenses(db, tenant_id="selected-ledger", after=50)
    assert page == rows[:25] and cursor == next_after
    db.scalars.assert_called_once()
    compiled = db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert compiled.params == {"tenant_id_1": "selected-ledger", "id_1": 50, "param_1": 26}
    assert "ORDER BY expenses.id" in str(compiled)

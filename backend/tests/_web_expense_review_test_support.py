"""Existing real route/PG/browser preparation shared by expense review consumers."""
import socket
import threading
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.models import Expense
from app.routes import (
    _web_expense_edit_command,
    _web_expense_fact,
    _web_expense_fx,
    _web_expense_helpers,
    _web_expense_offset_fact,
    web_expense_edit,
    web_pending,
)
from app.services import manual_expense_draft_presenter
from app.services.currency_binding_service import resolve_write_capability
from tests import _web_browser_test_support as browser_runtime
from tests.web_expense_fact_test_support import confirmation_actor


@pytest.fixture
def review_browser(confirmation_store, confirmation_web, monkeypatch):
    """Actual routes, commands, PostgreSQL receipts, templates and draft scripts."""
    client, options = confirmation_web
    scope = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account", "ledgerId": "owner", "deviceId": "browser"}

    with confirmation_store() as db:
        auth = confirmation_actor(db)
    def local(request: web_expense_edit.Request):
        request.state.web_session_auth = auth

    client.app.dependency_overrides[web_expense_edit.LocalOnly.dependency] = local
    monkeypatch.setattr(manual_expense_draft_presenter, "manual_draft_scope", lambda *args: scope)
    for module in (_web_expense_helpers, _web_expense_edit_command):
        monkeypatch.setattr(module, "calendar_revision", lambda *args, **kwargs: SimpleNamespace(timezone_name="Asia/Shanghai", revision=1))
    monkeypatch.setattr(_web_expense_helpers, "manual_draft_ack", lambda *args: None)
    monkeypatch.setattr(_web_expense_helpers, "expense_fx_view", lambda *args, **kwargs: None)
    monkeypatch.setattr(_web_expense_helpers, "_web_item_rows", lambda *args, **kwargs: {"rows": [], "status": "", "total_yuan": ""})
    monkeypatch.setattr(_web_expense_helpers, "web_split_rows", lambda *args, **kwargs: {"rows": [], "reconcile_state": "none"})
    monkeypatch.setattr(_web_expense_helpers, "web_split_members", lambda *args: [])
    monkeypatch.setattr(_web_expense_helpers, "list_ledger_category_options", lambda *args, **kwargs: ["购物"])
    monkeypatch.setattr(_web_expense_fx, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(_web_expense_fx, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    client.app.include_router(web_pending.router)
    monkeypatch.setattr(web_pending, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_pending, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_pending, "web_pending_enrichment_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(web_pending, "ledger_has_any_expense", lambda *args: True)
    client.app.mount("/static", StaticFiles(directory=Path(__file__).parents[1] / "app/static"))

    @client.app.get("/review-probe.js")
    def probe_script():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_recovery_probe.js", media_type="text/javascript")

    @client.app.get("/drawer-probe.js")
    def drawer_probe_script():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_drawer_probe.js", media_type="text/javascript")

    @client.app.middleware("http")
    async def attach_probe(request, call_next):
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        script = getattr(client.app.state, "expense_review_probe", None) or ("drawer-probe.js" if request.url.path == "/web/pending" else "review-probe.js")
        body = body.replace(b"</body>", b'<script src="/' + script.encode() + b'"></script></body>')
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body, status_code=response.status_code, headers=headers)

    yield client, scope


@pytest.fixture
def fact_review_browser(review_browser, confirmation_store, monkeypatch):
    """Real fact projection/history queries; empty related journals and controlled membership."""
    client, _ = review_browser
    monkeypatch.setattr(_web_expense_fact, "build_split_invite_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(_web_expense_fact.invitation_members, "list_members", lambda *args, **kwargs: [])
    monkeypatch.setattr(_web_expense_offset_fact, "current_ledger_date", lambda *args, **kwargs: date(2026, 10, 8))

    @client.app.post("/probe-later-fact")
    def later_fact():
        with confirmation_store() as db:
            resolve_write_capability(db)
            row = db.get(Expense, 42)
            row.merchant, row.amount_cents, row.row_version, row.status = "后来人工更正", 9900, 9, "confirmed"
            db.commit()
        return {"changed": True}

    @client.app.get("/navigation-probe.js")
    def navigation_probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_navigation_probe.js", media_type="text/javascript")

    client.app.state.expense_review_probe = "navigation-probe.js"
    return client


def _run_review_page(client, tmp_path, path, *, width=393):
    edge = browser_runtime._discover_database_browser()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", lifespan="off"))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.02)
            assert server.started
            return browser_runtime._edge_cdp().evaluate_page(edge, profile=tmp_path / "review-browser",
                prepare_url=lambda _: f"http://127.0.0.1:{port}" + path,
                width=width, height=960, expression="window.__expenseReviewResult || undefined",
                document_url_prefix=f"http://127.0.0.1:{port}/web/")
        finally:
            server.should_exit = True
            thread.join(timeout=8)

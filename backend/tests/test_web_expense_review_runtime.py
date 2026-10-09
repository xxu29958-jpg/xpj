"""Actual expense review consumers, with real command keys and controlled identity/financial transitions."""
import asyncio
import base64
import io
import json
import re
import socket
import threading
import time
from datetime import date, timedelta
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import uvicorn
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import JSON, Column, MetaData, Table, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError, app_error_handler
from app.middleware.logging import SanitizedLoggingMiddleware
from app.models import ApiIdempotencyKey, Expense, ExpenseOffsetFact, ExpenseOffsetRevision, ExpenseRevision
from app.routes import (
    _web_expense_edit_command,
    _web_expense_fact,
    _web_expense_fx,
    _web_expense_helpers,
    _web_expense_offset_fact,
    expenses,
    web_categories,
    web_duplicates,
    web_expense_create,
    web_expense_edit,
    web_expense_lifecycle,
    web_pending,
)
from app.schemas import ExpenseRelationshipImpacts, ExpenseResponse
from app.services import (
    category_service,
    expense_edit_command_service,
    expense_offset_service,
    expense_review_command_service,
    manual_expense_draft_presenter,
    pending_review_bulk_service,
)
from app.services.manual_expense_receipt import _manual_receipt_key
from tests import test_web_edge_runtime_contract as browser_runtime
from tests import test_web_expense_confirmation_page as page_tests
from tests import test_web_first_original as original_tests
from tests._web_native_form_support import hidden_post_forms

confirmation_store = page_tests.confirmation_store
confirmation_web = page_tests.confirmation_web
first_original_web = original_tests.first_original_web


@pytest.fixture
def slow_confirmation_script(monkeypatch):
    browser_runtime._discover_edge()
    respond = StaticFiles.get_response
    pending = True

    async def delayed(self, path, scope):
        nonlocal pending
        if pending and Path(path).as_posix() == "shared/confirm-modal.js":
            pending = False
            await asyncio.sleep(2)
        return await respond(self, path, scope)

    monkeypatch.setattr(StaticFiles, "get_response", delayed)
    yield
    assert not pending, "The delayed shared confirmation script was not requested"


def test_manual_original_follows_its_creation_receipt_without_losing_file_or_recreating_bill(
    first_original_web, monkeypatch, tmp_path,
):
    """Real native form/receipt/attachment; only financial creation and identity are controlled."""
    case = first_original_web
    case.client.app.include_router(web_expense_create.router)
    case.client.app.mount("/static", StaticFiles(directory=Path(__file__).parents[1] / "app/static"))
    monkeypatch.setattr(web_expense_create, "_list_ledger_options", lambda db: case.options)
    monkeypatch.setattr(web_expense_create, "_resolve_selected_ledger_id", lambda *a, **k: "owner")
    monkeypatch.setattr(web_expense_create, "_sidebar_counts", lambda *a: (0, 1))
    monkeypatch.setattr(web_expense_create, "manual_draft_scope", lambda *a: original_tests.SCOPE)
    monkeypatch.setattr(web_expense_create, "current_calendar", lambda *a, **k: SimpleNamespace(revision=1, timezone_name="Asia/Shanghai"))
    monkeypatch.setattr(web_expense_create, "list_ledger_category_options", lambda *a, **k: ["其他"])
    creations = []

    def create(db, payload, auth):
        assert payload.amount_cents == 1234 and payload.merchant == "原稿商家" and auth == original_tests.AUTH
        assert not creations, "The original creation must not be posted again to transfer its file"
        creations.append(payload.client_ref)
        row = db.get(Expense, 42)
        row.draft_idempotency_key = f"7:{payload.client_ref}"
        row.merchant, row.amount_cents = payload.merchant, payload.amount_cents
        row.original_currency_code, row.original_amount_minor = "CNY", payload.amount_cents
        snapshot = ExpenseResponse.model_validate(row).model_dump(mode="json")
        db.add(ApiIdempotencyKey(tenant_id="owner", idempotency_key=_manual_receipt_key(7, payload.client_ref),
            operation="create_manual_expense", request_fingerprint="b" * 64, status="succeeded",
            resource_type="expense", resource_id="42", response_body=snapshot,
            expires_at=row.created_at + timedelta(days=30)))
        db.commit()
        return row

    monkeypatch.setattr(web_expense_create, "create_manual_expense", create)
    sample = base64.b64encode(original_tests._camera_jpeg()).decode()
    probe = (Path(__file__).parent / "fixtures/manual_original_probe.js").read_text(encoding="utf-8")

    @case.client.app.middleware("http")
    async def manual_original_probe(request, call_next):
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        script = "<script>window.__originalSample=" + json.dumps(sample) + ";" + probe + "</script>"
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body.replace(b"</body>", script.encode() + b"</body>"), status_code=response.status_code, headers=headers)

    result = _run_review_page(case.client, tmp_path, "/web/expenses/new?ledger_id=owner&return_to=confirmed")
    assert "error" not in result, result
    assert result["rejected_preserved"] and result["transfer_retried"] and result["explicit_original_confirmation"]
    assert creations == [result["ref"]]
    with Session(case.engine) as db:
        row = db.get(Expense, 42)
        assert (row.merchant, row.amount_cents, row.row_version) == ("原稿商家", 1234, 5)
        assert row.image_path and row.image_hash
        receipts = db.scalars(select(ApiIdempotencyKey)).all()
        assert len(receipts) == 2
        original = next(r for r in receipts if r.operation == "attach_original")
        assert original.idempotency_key == result["ref"] and original.response_body["sha256"] == row.image_hash


def test_original_inspection_returns_to_its_page_and_refreshes_after_replenishment(first_original_web, tmp_path):
    from app.services.original_read_service import read_original_snapshot

    case = first_original_web
    case.client.app.mount("/static", StaticFiles(directory=Path(__file__).parents[1] / "app/static"))
    probe = (Path(__file__).parent / "fixtures/original_inspection_probe.js").read_text(encoding="utf-8")

    @case.client.app.middleware("http")
    async def inspection_probe(request, call_next):
        if request.url.path == "/web/expenses/44/original/health":
            await asyncio.sleep(0.25)
        response = await call_next(request)
        if "text/html" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        script = "<script>window.__originalSample=" + json.dumps(sample) + ";" + probe + "</script>"
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body.replace(b"</body>", script.encode() + b"</body>"), status_code=response.status_code, headers=headers)

    assert original_tests._attach(case).status_code == 200
    with Session(case.engine) as db:
        current = db.get(Expense, 42)
        values = {column.name: getattr(current, column.name) for column in Expense.__table__.columns}
        with read_original_snapshot(relative_path=current.image_path, tenant_id="owner",
                expected_sha256=current.image_hash) as image:
            sample = base64.b64encode(image.path.read_bytes()).decode()
        for number in [*range(1, 26), 43, 44]:
            row = dict(values, id=number, public_id=str(uuid4()), merchant=f"手工账单 {number}",
                image_path=None, thumbnail_path=None, image_hash=None)
            if number == 43:
                row.update(merchant="需要补回的小票", image_path="owner/missing.jpg", image_hash=current.image_hash)
            db.add(Expense(**row))
        db.commit()
        before = tuple(getattr(db.get(Expense, 43), name) for name in original_tests.FACT_FIELDS)
        version, digest = current.row_version, current.image_hash
    result = _run_review_page(case.client, tmp_path, "/web/originals?ledger_id=owner")
    assert "error" not in result, result
    assert result["page_retained"] and result["fresh_result"] and result["partial_read_failure"]
    with Session(case.engine) as db:
        row = db.get(Expense, 43)
        assert tuple(getattr(row, name) for name in original_tests.FACT_FIELDS) == before
        assert (row.row_version, row.image_hash) == (version + 1, digest)
        receipt = db.scalars(select(ApiIdempotencyKey).where(ApiIdempotencyKey.operation == "replenish_original")).one()
        assert receipt.status == "succeeded" and receipt.target_id == "43"
        with read_original_snapshot(relative_path=row.image_path, tenant_id="owner", expected_sha256=digest) as image:
            assert base64.b64encode(image.path.read_bytes()).decode() == sample


@pytest.fixture
def uncategorized_browser(review_browser, confirmation_store, monkeypatch):
    client, scope = review_browser
    client.app.include_router(web_categories.router)
    monkeypatch.setattr(web_categories, "_list_ledger_options", web_pending._list_ledger_options)
    monkeypatch.setattr(web_categories, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_categories, "list_ledger_category_options", lambda *args, **kwargs: [*category_service.DEFAULT_CATEGORIES, "自选分类"])

    def update(db, expense_id, tenant_id, payload, *, commit=True):
        row = db.get(Expense, expense_id)
        assert row.tenant_id == tenant_id
        assert payload.model_fields_set == {"category", "expected_row_version"}
        if row.status != "pending" or row.row_version != payload.expected_row_version:
            raise AppError("state_conflict", status_code=409)
        row.category = payload.category
        row.row_version += 1
        db.flush()
        if commit:
            db.commit()
        return row

    monkeypatch.setattr(pending_review_bulk_service, "update_expense", update)
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        row.category = ""
        for identity, category, status, tenant in [(43, "其他", "pending", "owner"),
            (44, "未分类", "pending", "owner"), (45, "", "confirmed", "owner"),
            (46, "", "pending", "other-ledger")]:
            copy = Expense(**{column.name: getattr(row, column.name) for column in Expense.__table__.columns
                if column.name not in {"id", "public_id", "category", "status", "tenant_id"}},
                id=identity, public_id=f"category-{identity}", category=category, status=status, tenant_id=tenant)
            copy.merchant = {43: "主动选择其他", 44: "金额还未核对", 45: "已经入账", 46: "另一账本"}[identity]
            if identity == 44:
                copy.amount_cents = copy.original_amount_minor = None
            db.add(copy)
        db.commit()
    return client, scope


def test_uncategorized_stale_selection_cannot_replace_later_category(uncategorized_browser, confirmation_store):
    client, scope = uncategorized_browser
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        row.category, row.row_version = "医疗", 5
        db.commit()
    result = client.post("/web/categories/uncategorized/bulk-set", data={"ledger_id": "owner",
        "draft_scope": json.dumps(scope), "idempotency_key": str(uuid4()), "expense_ids": ["42"], "expected_row_version": ["4"],
        "category": "购物"}, follow_redirects=False)
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        assert (row.category, row.row_version, row.status) == ("医疗", 5, "pending"), result.text
    assert "购物" in result.text and 'value="42:4"' in result.text


def test_uncategorized_partial_result_keeps_scope_money_and_original_selection(uncategorized_browser, confirmation_store):
    client, scope = uncategorized_browser
    page = client.get("/web/categories/uncategorized?ledger_id=owner")
    assert "主动选择其他" not in page.text
    assert "已经入账" not in page.text and "另一账本" not in page.text
    assert "JPY" in page.text and "2,850" in page.text and "金额待补" in page.text
    assert "主动选择其他" in client.get("/web/categories/uncategorized?ledger_id=owner&filter=including_other").text
    href = unescape(re.search(r'href="([^"]*/web/expenses/42/edit[^"]*)"', page.text)[1])
    detail = client.get(href)
    assert '/web/categories/uncategorized?ledger_id=owner' in detail.text
    with Session(confirmation_store) as db:
        row = db.get(Expense, 44)
        row.category, row.row_version = "交通", 5
        db.commit()
    result = client.post("/web/categories/uncategorized/bulk-set", data={"ledger_id": "owner",
        "draft_scope": json.dumps(scope), "idempotency_key": str(uuid4()), "expense_snapshot": ["42:4", "44:4"], "category": "自选分类"}, follow_redirects=False)
    assert "已更新 1 条" in result.text and "跳过 1 条" in result.text
    assert "刷新后重新选择" not in result.text
    assert re.search(r'name="expense_snapshot" value="44:4"[^>]*checked', result.text)
    assert "自选分类" in result.text and 'aria-label="继续逐笔核对"' in result.text
    with Session(confirmation_store) as db:
        saved, stale = db.get(Expense, 42), db.get(Expense, 44)
        assert (saved.category, saved.row_version, saved.status) == ("自选分类", 5, "pending")
        assert (saved.original_currency_code, saved.original_amount_minor, saved.amount_cents) == ("JPY", 2850, 12860)
        assert (stale.category, stale.row_version, stale.amount_cents, stale.status) == ("交通", 5, None, "pending")
        assert db.get(Expense, 43).category == "其他"
        # The category dashboard uses the same missing bucket, keeping chosen 其他 separate.
        counts = category_service._pending_counts_by_category(db, tenant_id="owner")
        assert counts == {"交通": 1, "自选分类": 1, "其他": 1}


def test_uncategorized_replay_returns_original_batch_after_later_edits(uncategorized_browser, confirmation_store):
    client, scope = uncategorized_browser
    original = {"ledger_id": "owner", "draft_scope": json.dumps(scope), "idempotency_key": str(uuid4()),
        "draft_ref": str(uuid4()), "expense_snapshot": ["42:4", "44:4"], "category": "购物"}
    first = client.post("/web/categories/uncategorized/bulk-set", data=original)
    assert "已更新 2 条" in first.text
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        row.category, row.row_version = "医疗", 8
        db.commit()
    replay = client.post("/web/categories/uncategorized/bulk-set", data=original)
    assert "已更新 2 条" in replay.text, "The first accepted batch must survive response loss and later edits"
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).category, db.get(Expense, 42).row_version) == ("医疗", 8)
        assert (db.get(Expense, 44).category, db.get(Expense, 44).row_version) == ("购物", 5)
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == original["idempotency_key"]))


def test_uncategorized_original_survives_detail_return_lost_reply_and_partial_continuation(
    uncategorized_browser, confirmation_store, tmp_path,
):
    client, _ = uncategorized_browser
    client.app.state.expense_review_probe = "category-recovery-probe.js"

    @client.app.get("/category-recovery-probe.js")
    def category_probe():
        return FileResponse(Path(__file__).parent / "fixtures/category_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/category-later/{stage}")
    def later_category(stage: str):
        with Session(confirmation_store) as db:
            row = db.get(Expense, 44 if stage == "before" else 42)
            row.category, row.row_version = ("交通", 8) if stage == "before" else ("医疗", 9)
            db.commit()
        return {"changed": True}

    result = _run_review_page(client, tmp_path, "/web/categories/uncategorized?ledger_id=owner")
    assert "error" not in result, result
    assert result["detail_return"] and result["original_restored"] and result["partial_continued"]
    first, replay, final = result["requests"]
    assert first == replay and final != first
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).category, db.get(Expense, 42).row_version) == ("医疗", 9)
        assert (db.get(Expense, 44).category, db.get(Expense, 44).row_version) == ("自选分类", 9)
        assert db.get(Expense, 42).original_amount_minor == 2850
        assert db.get(Expense, 44).amount_cents is None
        assert all(db.get(Expense, identity).status == "pending" for identity in (42, 44))
        receipts = db.scalars(select(ApiIdempotencyKey)).all()
        assert len(receipts) == 2
        original = next(row for row in receipts if row.idempotency_key == result["command"])
        assert original.response_body["result"]["success_ids"] == [42]


@pytest.mark.parametrize("failure", ["role", "binding", "database"])
def test_uncategorized_failure_retains_original_selection(uncategorized_browser, confirmation_store, monkeypatch, failure):
    client, scope = uncategorized_browser
    if failure == "role":
        web_categories._list_ledger_options(None)[0].role = "viewer"
    elif failure == "binding":
        scope = {**scope, "deviceId": "previous-device"}
    else:
        update = pending_review_bulk_service.update_expense

        def fail_second(db, expense_id, *args, **kwargs):
            if expense_id == 44:
                raise SQLAlchemyError("controlled storage interruption")
            return update(db, expense_id, *args, **kwargs)

        monkeypatch.setattr(pending_review_bulk_service, "update_expense", fail_second)
    original = {"ledger_id": "owner", "category": "自选分类", "draft_scope": json.dumps(scope),
        "expense_snapshot": ["42:4", "44:4"], "filter": "including_other", "idempotency_key": str(uuid4())}
    response = client.post("/web/categories/uncategorized/bulk-set", data=original, follow_redirects=False)
    assert response.status_code == {"role": 403, "binding": 409, "database": 503}[failure], response.text
    form = hidden_post_forms(response.text)["/web/categories/uncategorized/bulk-set"]
    for key, value in original.items():
        if isinstance(value, list):
            assert [unescape(entry) for entry in re.findall(rf'name="{key}" value="([^"]*)"', response.text)] == value
        else:
            assert form[key] == value
    assert "controlled storage interruption" not in response.text
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).category == ""
        assert (db.get(Expense, 44).category, db.get(Expense, 44).row_version) == ("未分类", 4)
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == original["idempotency_key"])) is None


@pytest.fixture
def review_browser(confirmation_store, confirmation_web, monkeypatch):
    """Actual routes, templates and draft scripts; SQLite keys with a controlled financial transition."""
    client, options = confirmation_web
    scope = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account", "ledgerId": "owner", "deviceId": "browser"}

    def local(request: web_expense_edit.Request):
        request.state.web_session_auth = SimpleNamespace(ledger_id="owner")

    def update(db, expense_id, tenant_id, payload, **kwargs):
        current = db.get(Expense, expense_id)
        if current.status != "pending" or current.row_version != payload.expected_row_version:
            raise AppError("state_conflict", status_code=409)
        if "merchant" in payload.model_fields_set:
            current.merchant = payload.merchant
        current.row_version += 1
        db.flush()
        return current

    client.app.dependency_overrides[web_expense_edit.LocalOnly.dependency] = local
    monkeypatch.setattr(manual_expense_draft_presenter, "manual_draft_scope", lambda *args: scope)
    monkeypatch.setattr(expense_edit_command_service, "update_expense", update)
    monkeypatch.setattr(expense_edit_command_service, "prepare_pending_expense_fx", lambda *args, **kwargs: None)
    monkeypatch.setattr(expense_review_command_service, "update_expense", update)
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
    monkeypatch.setattr(_web_expense_fx, "resolve_web_actor", lambda *args: (None, None))
    client.app.include_router(web_pending.router)
    monkeypatch.setattr(web_pending, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_pending, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_pending, "require_runtime_home_currency_code", lambda db: "CNY")
    monkeypatch.setattr(web_pending, "list_pending", lambda db, ledger: db.scalars(select(Expense).where(Expense.status == "pending").order_by(Expense.id)).all())
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
    metadata = MetaData()
    for model in (ExpenseOffsetFact, ExpenseOffsetRevision, ExpenseRevision):
        Table(model.__tablename__, metadata, *(Column(column.name,
            JSON() if isinstance(column.type, JSONB) else column.type, primary_key=column.primary_key)
            for column in model.__table__.columns))
    metadata.create_all(confirmation_store)
    monkeypatch.setattr(expense_offset_service, "expense_to_response", lambda db, *, expense, tenant_id: ExpenseResponse.model_validate(expense))
    monkeypatch.setattr(expense_offset_service, "relationship_impacts", lambda *args, **kwargs: ExpenseRelationshipImpacts())
    monkeypatch.setattr(_web_expense_fact, "build_split_invite_context", lambda *args, **kwargs: None)
    monkeypatch.setattr(_web_expense_fact.invitation_members, "list_members", lambda *args, **kwargs: [])
    monkeypatch.setattr(_web_expense_offset_fact, "current_ledger_date", lambda *args, **kwargs: date(2026, 10, 8))

    @client.app.post("/probe-later-fact")
    def later_fact():
        with Session(confirmation_store) as db:
            row = db.get(Expense, 42)
            row.merchant, row.amount_cents, row.row_version, row.status = "后来人工更正", 9900, 9, "confirmed"
            db.commit()
        return {"changed": True}

    @client.app.get("/navigation-probe.js")
    def navigation_probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_navigation_probe.js", media_type="text/javascript")

    client.app.state.expense_review_probe = "navigation-probe.js"
    return client


@pytest.fixture
def related_review_browser(review_browser, confirmation_store, monkeypatch):
    client, _ = review_browser
    options = [SimpleNamespace(ledger_id="owner", name="家庭账本", role="owner", is_default=True)]

    def keep(db, expense_id, tenant_id, *, expected_row_version, commit=True):
        current = db.get(Expense, expense_id)
        if current.row_version != expected_row_version:
            raise AppError("state_conflict", status_code=409)
        current.duplicate_status, current.row_version = "none", current.row_version + 1
        db.flush()
        if commit:
            db.commit()
        return current

    def reject(db, expense_id, tenant_id, *, expected_row_version, **kwargs):
        current = db.get(Expense, expense_id)
        if current.row_version != expected_row_version or current.status != "pending":
            raise AppError("state_conflict", status_code=409)
        current.status, current.row_version = "rejected", current.row_version + 1
        db.flush()
        return current

    def undo(db, expense_id, tenant_id, expected_row_version, **kwargs):
        current = db.get(Expense, expense_id)
        if current.row_version != expected_row_version or current.status != "rejected":
            raise AppError("state_conflict", status_code=409)
        current.status, current.row_version = "pending", current.row_version + 1
        db.flush()
        return current

    monkeypatch.setattr(expense_review_command_service, "reject_expense", reject)
    monkeypatch.setattr(expense_review_command_service, "undo_reject_expense", undo)
    client.app.include_router(web_duplicates.router)
    monkeypatch.setattr(web_duplicates, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_duplicates, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_duplicates, "require_runtime_home_currency_code", lambda db: "CNY")
    monkeypatch.setattr(expense_review_command_service, "mark_expense_not_duplicate", keep)

    @client.app.get("/actions-probe.js")
    def actions_probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_actions_probe.js", media_type="text/javascript")

    client.app.state.expense_review_probe = "actions-probe.js"
    return client


def _related_keep_fields():
    return {"ledger_id": "owner", "expected_row_version": "4", "idempotency_key": str(uuid4()),
        "keep_idempotency_key": str(uuid4()), "reject_idempotency_key": str(uuid4()),
        "merchant": "原填写仍未保存", "amount_yuan": "002850", "original_currency": "JPY", "category": "购物",
        "save_before_confirm": "1", "draft_ref": str(uuid4()), "return_to": "pending", "return_filter": "duplicate",
        "draft_scope": json.dumps({"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account",
            "ledgerId": "owner", "deviceId": "browser"})}


@pytest.mark.parametrize("action", ["reject", "undo", "reject-current", "reject-original"])
@pytest.mark.parametrize("original_device", ["", "previous-browser"])
def test_ignore_and_undo_preserve_original_identity_before_mutation(
    related_review_browser, confirmation_store, action, original_device,
):
    fields = _related_keep_fields()
    fields["draft_scope"] = json.dumps({**json.loads(fields["draft_scope"]), "deviceId": original_device}) if original_device else ""
    fields.update(original_expense_id="41", expected_original_row_version="1")
    if action == "undo":
        with Session(confirmation_store) as db:
            db.get(Expense, 42).status = "rejected"
            db.commit()
    path = f"/web/{'duplicates' if action.startswith('reject-') else 'expenses'}/42/{action}"
    response = related_review_browser.post(path, data=fields, follow_redirects=False)
    assert response.status_code == 409, response.text
    assert 'name="draft_scope"' in response.text
    refused = related_review_browser.post(path, data=fields, headers={"Accept": "application/json"})
    assert refused.status_code == 409 and refused.json()["draft_result"] == "blocked"
    assert "ack" not in refused.json()
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        assert (row.row_version, row.status) == (4, "rejected" if action == "undo" else "pending")
        assert not db.scalars(select(ApiIdempotencyKey)).all()


@pytest.mark.parametrize("fragment", ["0", "1"])
def test_ignore_conflict_returns_the_original_raw_financial_input(related_review_browser, confirmation_store, fragment):
    fields = {**_related_keep_fields(), "expected_row_version": "3", "fragment": fragment}
    response = related_review_browser.post("/web/expenses/42/reject", data=fields, follow_redirects=False)
    assert response.status_code == 409, response.text
    for name in ("merchant", "amount_yuan", "idempotency_key", "reject_idempotency_key", "draft_ref", "expected_row_version"):
        assert re.search(rf'name="{name}"\s+value="{re.escape(fields[name])}"', response.text), name
    assert 'name="return_filter" value="duplicate"' in response.text
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        assert (row.status, row.merchant, row.row_version) == ("pending", "首次便利店", 4)


@pytest.mark.parametrize("action", ["reject", "undo"])
def test_ignore_or_undo_replay_recognizes_original_after_later_confirmation(
    related_review_browser, confirmation_store, action,
):
    fields = _related_keep_fields()
    if action == "undo":
        with Session(confirmation_store) as db:
            db.get(Expense, 42).status = "rejected"
            db.commit()
    path = f"/web/expenses/42/{action}"
    first = related_review_browser.post(path, data=fields, follow_redirects=False)
    assert first.status_code == 303, first.text
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        row.status, row.row_version, row.merchant = "confirmed", 9, "后来入账"
        db.commit()
    replay = related_review_browser.post(path, data=fields, follow_redirects=False)
    assert replay.status_code == 303, replay.text
    receipt = related_review_browser.post(path, data=fields, headers={"Accept": "application/json"}).json()
    assert (receipt["receipt"]["status"], receipt["receipt"]["row_version"]) == ("rejected" if action == "reject" else "pending", 5)
    assert receipt["ack"]["clientRef"] == fields["reject_idempotency_key" if action == "reject" else "idempotency_key"]
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        assert (row.status, row.row_version, row.merchant) == ("confirmed", 9, "后来入账")
        assert len(db.scalars(select(ApiIdempotencyKey)).all()) == 1


@pytest.mark.parametrize("failure,status", [(AppError("state_conflict", status_code=409), 409), (SQLAlchemyError("storage unavailable"), 503)])
@pytest.mark.parametrize("origin,domain", [("pending", "inbox"), ("recurring_occurrence", "plans")])
def test_ignore_and_undo_failures_retain_original_command_without_claiming_expiry(
    related_review_browser, confirmation_store, monkeypatch, caplog, failure, status, origin, domain,
):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(web_expense_lifecycle, "submit_expense_rejection", fail)
    related_review_browser.app.add_middleware(SanitizedLoggingMiddleware)
    fields = _related_keep_fields()
    fields.update(return_to=origin, return_recurring_public_id=str(uuid4()), return_month="2026-10")
    response = related_review_browser.post("/web/expenses/42/undo", data=fields, follow_redirects=False)
    assert response.status_code == status, response.text
    assert "超过 5 分钟" not in response.text
    assert f'data-domain="{domain}"' in response.text
    current_link = re.search(r'href="([^"]+)">查看账单当前状态', response.text)
    assert current_link and f"return_to={origin}" in current_link.group(1)
    retained = hidden_post_forms(response.text)["/web/expenses/42/undo"]
    for name in ("idempotency_key", "expected_row_version", "draft_scope", "return_filter"):
        assert retained[name] == fields[name]
    responses = [response]
    for action in ("reject", "undo"):
        refused = related_review_browser.post(f"/web/expenses/42/{action}", data=fields,
            headers={"Accept": "application/json"})
        assert refused.status_code == status, refused.text
        assert refused.json()["draft_result"] == ("rejected" if action == "reject" and status == 409 else "blocked")
        assert "ack" not in refused.json()
        responses.append(refused)
    errors = [record for record in caplog.records if record.name == "ticketbox.http"]
    if status >= 500:
        for failed_response in responses:
            assert any(record.exc_info and record.exc_info[1] is failure
                and failed_response.headers["X-Request-Id"] in record.getMessage() for record in errors)
            assert str(failure) not in failed_response.text
    else:
        assert not errors
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).row_version == 4


@pytest.mark.parametrize("action", ["reject", "undo"])
def test_ignore_and_undo_refuse_viewer_before_loading_a_missing_target(related_review_browser, monkeypatch, action):
    monkeypatch.setattr(web_expense_lifecycle, "_list_ledger_options", lambda db: [SimpleNamespace(
        ledger_id="owner", name="家庭账本", role="viewer", is_default=True)])
    response = related_review_browser.post(f"/web/expenses/999/{action}", data=_related_keep_fields(), follow_redirects=False)
    assert response.status_code == 403, response.text
    refused = related_review_browser.post(f"/web/expenses/999/{action}", data=_related_keep_fields(), headers={"Accept": "application/json"})
    assert refused.status_code == 403 and refused.json()["draft_result"] == "blocked"


def test_original_ignore_banner_does_not_acquire_a_later_rejection(related_review_browser, confirmation_store):
    first = related_review_browser.post("/web/expenses/42/reject", data=_related_keep_fields(), follow_redirects=False)
    assert first.status_code == 303
    page = related_review_browser.get(first.headers["location"])
    original = hidden_post_forms(page.text)["/web/expenses/42/undo"]
    assert original["expected_row_version"] == "5"
    with Session(confirmation_store) as db:
        db.get(Expense, 42).row_version = 9
        db.commit()
    reopened = related_review_browser.get(first.headers["location"])
    assert '/web/expenses/42/undo' not in hidden_post_forms(reopened.text), "original banner retargeted a later ignore"
    task = related_review_browser.get(f'/web/expenses/42/undo?ledger_id=owner&undo_version=5&undo_key={original["idempotency_key"]}')
    resumed = hidden_post_forms(task.text)["/web/expenses/42/undo"]
    assert (resumed["expected_row_version"], resumed["idempotency_key"]) == ("5", original["idempotency_key"])
    refused = related_review_browser.post("/web/expenses/42/undo", data=resumed, headers={"Accept": "application/json"})
    assert refused.status_code == 409 and refused.json()["draft_result"] == "blocked"
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).row_version, db.get(Expense, 42).status) == (9, "rejected")


@pytest.mark.parametrize("entry,later_ignore", [("drawer", False), ("full", True)])
def test_ignore_and_undo_unknown_results_recover_original_commands_and_financial_input(
    related_review_browser, confirmation_store, tmp_path, entry, later_ignore, slow_confirmation_script,
):
    client = related_review_browser

    @client.app.get("/ignore-recovery-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_ignore_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/ignore-later")
    def later():
        with Session(confirmation_store) as db:
            row = db.get(Expense, 42)
            assert (row.status, row.row_version) == ("pending", 6)
            row.status, row.row_version, row.merchant = "rejected", 9, "同伴后来再次忽略"
            db.commit()
        return {"changed": True}

    @client.app.get("/ignore-current")
    def current():
        with Session(confirmation_store) as db:
            row = db.get(Expense, 42)
            return {"version": row.row_version, "status": row.status, "merchant": row.merchant}

    client.app.state.expense_review_probe = "ignore-recovery-probe.js"
    path = "/web/pending?ledger_id=owner&filter=ready" if entry == "drawer" else "/web/expenses/42/edit?ledger_id=owner&return_to=pending&return_filter=ready"
    result = _run_review_page(client, tmp_path, path + f"&entry={entry}&later={int(later_ignore)}", width=1440)
    assert "error" not in result, json.dumps(result, ensure_ascii=False)
    assert result["financial_retained"] and result["reject_lost"] and result["undo_lost"]
    assert result["requests"]["reject"][0] == result["requests"]["reject"][1]
    assert result["requests"]["undo"][0] == result["requests"]["undo"][1]
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        assert (row.status, row.merchant) == (("rejected", "同伴后来再次忽略") if later_ignore else ("confirmed", "忽略前的原填写"))


def test_duplicate_review_keeps_both_originals_currency_and_group_return(related_review_browser, fact_review_browser, confirmation_store):
    client = related_review_browser
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        for identity, status in [(43, "confirmed"), (44, "pending")]:
            copy = Expense(**{c.name: getattr(current, c.name) for c in Expense.__table__.columns
                if c.name not in {"id", "public_id"}}, id=identity, public_id=f"comparison-{identity}")
            copy.status = status
            copy.duplicate_status, copy.duplicate_of_id = ("none", None) if identity == 43 else ("suspected", 43)
            if identity == 43:
                copy.original_currency_code, copy.original_amount_minor = "CNY", 12860
            copy.image_path = f"comparison-{identity}.png"
            db.add(copy)
        current.duplicate_status, current.duplicate_of_id = "suspected", 43
        current.image_path = "comparison-42.png"
        db.commit()
    page = client.get("/web/duplicates?ledger_id=owner&focus=42")
    pair = re.search(r'id="duplicate-42".*?</section>', page.text, re.S)
    assert pair
    for identity in (42, 43):
        link = re.search(r'href="(/web/expenses/' + str(identity) + r'/edit\?[^"]+)"', pair.group(0))
        assert link, "the comparison must open each actual bill"
        details = client.get(unescape(link.group(1)))
        assert '/web/duplicates?ledger_id=owner&amp;focus=42' in details.text
        assert f'/web/expenses/{identity}/image?ledger_id=owner' in page.text
    assert "JPY" in page.text and "CNY" in page.text
    assert 'class="duplicate-money is-different"' in pair.group(0), "equal home projections must not hide different original currencies"
    action = "/web/duplicates/42/keep"
    response = client.post(action, data=hidden_post_forms(page.text)[action], follow_redirects=False)
    assert response.status_code == 303
    assert "focus=44" in response.headers["location"]
    returned = client.get(response.headers["location"])
    assert 'id="duplicate-44"' in returned.text and 'autofocus' in returned.text
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).status, db.get(Expense, 42).duplicate_status) == ("pending", "none")
        assert db.get(Expense, 43).status == "confirmed"
        assert db.get(Expense, 44).duplicate_status == "suspected"


@pytest.mark.parametrize("entry,fault", [("drawer", "reply"), ("full", "reply"), ("drawer", "ack-store"), ("drawer", "rejected")])
def test_keep_original_survives_reload_then_rejoins_financial_draft(related_review_browser, confirmation_store, tmp_path, entry, fault):
    client = related_review_browser
    with Session(confirmation_store) as db:
        db.get(Expense, 42).duplicate_status = "suspected"
        db.commit()

    @client.app.get("/keep-recovery-probe.js")
    def recovery_probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_keep_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/keep-later")
    def later():
        with Session(confirmation_store) as db:
            row = db.get(Expense, 42)
            row.row_version, row.merchant = 9, "后来填写"
            row.duplicate_status = "none" if (entry, fault) == ("drawer", "reply") else "suspected"
            db.commit()
        return {"changed": True}

    @client.app.get("/keep-current")
    def current():
        with Session(confirmation_store) as db:
            row = db.get(Expense, 42)
            return {"version": row.row_version, "duplicate": row.duplicate_status, "merchant": row.merchant}

    client.app.state.expense_review_probe = "keep-recovery-probe.js"
    path = "/web/pending?ledger_id=owner&filter=duplicate" if entry == "drawer" else "/web/expenses/42/edit?ledger_id=owner&return_to=pending&return_filter=duplicate"
    result = _run_review_page(client, tmp_path, path + f"&entry={entry}&fault={fault}", width=1440)
    assert "error" not in result, result
    assert result["original_preserved"] and result["confirmed"]
    assert result["rejected" if fault == "rejected" else "storeFailed" if fault == "ack-store" else "lost"]
    if fault == "rejected":
        assert len(result["requests"]) == 1
    else:
        assert len(result["requests"]) == 2 and result["requests"][0] == result["requests"][1]
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        assert (row.status, row.merchant, row.amount_cents) == ("confirmed", "非重复前的原填写", 12860)


def test_full_keep_returns_to_original_review_without_saving_raw_input(related_review_browser, confirmation_store):
    fields = _related_keep_fields()
    response = related_review_browser.post("/web/duplicates/42/keep", data=fields, follow_redirects=False)
    assert response.status_code == 200, response.headers.get("location")
    for name in ("merchant", "amount_yuan", "draft_ref", "idempotency_key", "keep_idempotency_key", "expected_row_version"):
        assert re.search(rf'name="{name}"\s+value="{re.escape(fields[name])}"', response.text), name
    assert 'data-expensereview-row-version="5"' in response.text
    assert '/web/pending?ledger_id=owner&amp;filter=duplicate' in response.text
    buttons = {label: attributes for attributes, label in re.findall(r'<button\b([^>]*)>([^<]*)</button>', response.text)}
    assert "disabled" in buttons["保存草稿"] and "disabled" in buttons["确认入账"]
    assert "disabled" not in buttons["核对当前记录，保留填写"]
    assert re.search(r'<button\b[^>]*aria-hidden="true"[^>]*disabled', response.text)
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        assert (row.status, row.merchant, row.row_version) == ("pending", "首次便利店", 5)


def test_related_keep_replay_recognizes_original_decision_without_overwriting_later_state(related_review_browser, confirmation_store, monkeypatch):
    fields = {**_related_keep_fields(), "fragment": "1"}
    assert related_review_browser.post("/web/duplicates/42/keep", data=fields).status_code == 200
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        row.duplicate_status, row.row_version, row.merchant = "suspected", 9, "后来记录"
        db.commit()
    replay = related_review_browser.post("/web/duplicates/42/keep", data=fields, headers={"Accept": "application/json"})
    assert replay.status_code == 200, replay.text
    result = replay.json()
    assert result["receipt"] == {"operation": "mark_not_duplicate", "expense_id": 42,
        "accepted": True, "decision_key": fields["keep_idempotency_key"]}
    assert result["ack"] == {"scope": json.loads(fields["draft_scope"]), "clientRef": fields["keep_idempotency_key"]}
    assert result["next"].endswith("&confirmation_task=1#expensereview-edit-" + fields["draft_ref"])
    monkeypatch.setattr(web_duplicates, "_list_ledger_options", lambda db: [SimpleNamespace(
        ledger_id="owner", name="家庭账本", role="viewer", is_default=True)])
    denied = related_review_browser.post("/web/duplicates/42/keep", data=fields, headers={"Accept": "application/json"})
    assert denied.status_code == 403 and "receipt" not in denied.json()
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        assert (row.duplicate_status, row.row_version, row.merchant) == ("suspected", 9, "后来记录")


@pytest.mark.parametrize("captured_scope,status,fragment", [("", 409, "0"), ("previous-browser", 409, "1"), ("viewer", 403, "0")])
def test_related_keep_refuses_changed_or_missing_original_identity(related_review_browser, confirmation_store, monkeypatch, captured_scope, status, fragment):
    fields = {**_related_keep_fields(), "fragment": fragment}
    if captured_scope == "viewer":
        monkeypatch.setattr(web_duplicates, "_list_ledger_options", lambda db: [SimpleNamespace(ledger_id="owner", name="家庭账本", role="viewer", is_default=True)])
    else:
        fields["draft_scope"] = json.dumps({**json.loads(fields["draft_scope"]), "deviceId": captured_scope}) if captured_scope else ""
    response = related_review_browser.post("/web/duplicates/42/keep", data=fields, follow_redirects=False)
    assert response.status_code == status, response.text
    assert re.search(r'name="merchant"\s+value="原填写仍未保存"', response.text)
    assert 'name="return_filter" value="duplicate"' in response.text
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).row_version == 4


@pytest.mark.parametrize("action", ["keep", "reject-current", "reject-original"])
def test_standalone_duplicate_form_carries_its_original_decision_and_browser_identity(related_review_browser, confirmation_store, action):
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        db.add(Expense(**{column.name: getattr(current, column.name) for column in Expense.__table__.columns
            if column.name not in {"id", "public_id"}}, id=43, public_id="comparison-expense"))
        current.duplicate_status, current.duplicate_of_id = "suspected", 43
        db.commit()
    page = related_review_browser.get("/web/duplicates?ledger_id=owner")
    path = f"/web/duplicates/42/{action}"
    fields = hidden_post_forms(page.text)[path]
    key = fields["idempotency_key"]
    assert json.loads(fields["draft_scope"])["deviceId"] == "browser"
    response = related_review_browser.post(path, data=fields, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/web/duplicates?")
    with Session(confirmation_store) as db:
        current, original = db.get(Expense, 42), db.get(Expense, 43)
        assert (current.status, original.status) == (
            ("rejected", "pending") if action == "reject-current" else
            ("pending", "rejected") if action == "reject-original" else ("pending", "pending"))
        current.merchant, current.row_version, current.duplicate_status = "后来修改本次", 9, "suspected"
        original.merchant, original.row_version, original.status = "后来修改参考", 11, "confirmed"
        db.commit()
    replay = related_review_browser.post(path, data=fields, headers={"Accept": "application/json"}, follow_redirects=False)
    assert replay.status_code == 200, replay.text
    assert replay.json()["ack"]["clientRef"] == key
    assert replay.json()["next"].startswith("/web/duplicates?")
    assert replay.json()["receipt"]["accepted"] is True
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).merchant, db.get(Expense, 42).row_version, db.get(Expense, 42).duplicate_status) == ("后来修改本次", 9, "suspected")
        assert (db.get(Expense, 43).merchant, db.get(Expense, 43).row_version, db.get(Expense, 43).status) == ("后来修改参考", 11, "confirmed")
        assert len(db.scalars(select(ApiIdempotencyKey)).all()) == 1


@pytest.mark.parametrize("action", ["keep", "reject-current", "reject-original", "decision"])
def test_standalone_decision_preserves_writer_permission_denial(related_review_browser, confirmation_store, monkeypatch, action):
    related_review_browser.app.add_exception_handler(AppError, app_error_handler)
    monkeypatch.setattr(web_duplicates, "_list_ledger_options", lambda db: [SimpleNamespace(
        ledger_id="owner", name="家庭账本", role="viewer", is_default=True)])
    response = related_review_browser.post(f"/web/duplicates/42/{action}", data={"ledger_id": "owner"},
        headers={"Accept": "application/json"}, follow_redirects=False)
    assert response.status_code == 403, response.text
    assert response.json()["error"] == "permission_denied"
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).row_version == 4
        assert db.scalar(select(ApiIdempotencyKey)) is None


@pytest.mark.parametrize("action,command", [("keep", "submit_expense_duplicate_decision"),
    ("reject-current", "submit_expense_rejection"), ("reject-original", "reject_duplicate_original_keep_current")])
def test_standalone_decision_storage_failure_retains_original_and_reports_cause(
    related_review_browser, confirmation_store, monkeypatch, caplog, action, command,
):
    failure = SQLAlchemyError("controlled duplicate storage interruption")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(web_duplicates, command, fail)
    related_review_browser.app.add_middleware(SanitizedLoggingMiddleware)
    fields = {**_related_keep_fields(), "original_expense_id": "43", "expected_original_row_version": "4",
        "return_duplicate_expense_id": "44", "save_before_confirm": "0"}
    path = f"/web/duplicates/42/{action}"
    native = related_review_browser.post(path, data=fields, follow_redirects=False)
    retained = hidden_post_forms(native.text)[path]
    for name in ("expected_row_version", "idempotency_key", "draft_scope", "return_duplicate_expense_id"):
        assert retained[name] == fields[name]
    enhanced = related_review_browser.post(path, data=fields, headers={"Accept": "application/json"})
    assert enhanced.json()["draft_result"] == "blocked" and "ack" not in enhanced.json()
    for response in (native, enhanced):
        assert response.status_code == 503 and str(failure) not in response.text
        assert any(record.name == "ticketbox.http" and record.exc_info and record.exc_info[1] is failure
            and response.headers["X-Request-Id"] in record.getMessage() for record in caplog.records)
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).row_version == 4
        assert db.scalar(select(ApiIdempotencyKey)) is None


@pytest.mark.parametrize("action,fault", [("keep", "reply"), ("reject-current", "reply"), ("reject-original", "reply"), ("keep", "conflict")])
def test_standalone_decision_recovers_original_or_explicitly_reviews_a_refusal(
    related_review_browser, confirmation_store, tmp_path, action, fault, slow_confirmation_script,
):
    client = related_review_browser
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        db.add(Expense(**{c.name: getattr(row, c.name) for c in Expense.__table__.columns
            if c.name not in {"id", "public_id"}}, id=43, public_id="original-comparison"))
        row.duplicate_status, row.duplicate_of_id = "suspected", 43
        db.commit()

    @client.app.get("/duplicate-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/duplicate_decision_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/duplicate-peer")
    def peer():
        with Session(confirmation_store) as db:
            current, original = db.get(Expense, 42), db.get(Expense, 43)
            current.merchant, current.row_version, current.duplicate_status = "后来修改本次", 9, "suspected"
            original.merchant, original.row_version, original.status = "后来修改参考", 11, "confirmed"
            db.commit()
        return {"changed": True}

    @client.app.get("/duplicate-facts")
    def facts():
        with Session(confirmation_store) as db:
            current, original = db.get(Expense, 42), db.get(Expense, 43)
            return {"current_version": current.row_version, "current_merchant": current.merchant,
                "current_duplicate": current.duplicate_status, "original_version": original.row_version, "original_merchant": original.merchant,
                "receipt_count": len(db.scalars(select(ApiIdempotencyKey)).all())}

    client.app.state.expense_review_probe = "duplicate-probe.js"
    result = _run_review_page(client, tmp_path, f"/web/duplicates?ledger_id=owner&choice={action}&fault={fault}", width=393)
    assert "error" not in result, json.dumps(result, ensure_ascii=False)
    assert result["complete"]


@pytest.mark.parametrize("first_surface", ["api", "web"])
def test_keep_api_and_web_share_the_existing_original_decision(related_review_browser, confirmation_store, monkeypatch, first_surface):
    client = related_review_browser
    client.app.include_router(expenses.router)
    client.app.dependency_overrides[expenses.get_current_writer_context] = lambda: SimpleNamespace(tenant_id="owner", device_id=None)
    monkeypatch.setattr(expenses, "expense_to_response", expense_review_command_service.expense_to_response)
    fields = {**_related_keep_fields(), "fragment": "1"}

    def submit(surface):
        if surface == "web":
            return client.post("/web/duplicates/42/keep", data=fields)
        return client.post("/api/expenses/42/mark-not-duplicate", json={"expected_row_version": 4},
            headers={"Idempotency-Key": fields["keep_idempotency_key"]})

    first = submit(first_surface)
    assert first.status_code == 200, first.text
    with Session(confirmation_store) as db:
        row = db.get(Expense, 42)
        row.duplicate_status, row.row_version = "suspected", 9
        db.commit()
    replay = submit("web" if first_surface == "api" else "api")
    assert replay.status_code == 200, replay.text
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).duplicate_status, db.get(Expense, 42).row_version) == ("suspected", 9)
        assert [(r.operation, r.status) for r in db.scalars(select(ApiIdempotencyKey))] == [("mark_not_duplicate", "succeeded")]


def test_keep_decision_and_idempotency_record_roll_back_together(related_review_browser, confirmation_store, monkeypatch):
    def fail(*args, **kwargs):
        raise SQLAlchemyError("decision persistence failed")

    monkeypatch.setattr(expense_review_command_service, "mark_idempotency_succeeded", fail)
    with Session(confirmation_store) as db, pytest.raises(SQLAlchemyError, match="decision persistence failed"):
        expense_review_command_service.submit_expense_duplicate_decision(db, tenant_id="owner", expense_id=42,
            expected_row_version=4, request_expected_row_version=4, idempotency_key=str(uuid4()))
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).row_version == 4
        assert db.scalar(select(ApiIdempotencyKey)) is None


@pytest.mark.parametrize("action,entry", [("keep", "drawer"), ("reject", "drawer"), ("keep", "full")])
def test_related_review_actions_keep_input_and_rejoin_original_queue_before_confirmation(
    related_review_browser, confirmation_store, tmp_path, action, entry,
):
    if action == "keep":
        with Session(confirmation_store) as db:
            db.get(Expense, 42).duplicate_status = "suspected"
            db.commit()
    filter_name = "duplicate" if action == "keep" else "ready"
    path = f"/web/pending?ledger_id=owner&filter={filter_name}&probe={action}"
    if entry == "full":
        path = f"/web/expenses/42/edit?ledger_id=owner&return_to=pending&return_filter={filter_name}&probe={action}&entry=full"
    result = _run_review_page(related_review_browser, tmp_path, path, width=1440)
    assert "error" not in result, result
    assert result["input_retained"] and result["reviewed"] and result["confirmed"]
    if action == "keep" and entry == "drawer":
        assert result["keep_reply_lost"] and result["unknown_retained"]
    if action == "keep" and entry == "full":
        assert result["legacy_edit_restored"]
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.status, current.merchant, current.amount_cents) == ("confirmed", "相关操作前的填写", 12860)


@pytest.mark.parametrize("surface,operation", [("full", "confirm"), ("drawer", "confirm"), ("drawer", "save")])
def test_current_fact_returns_to_original_review_and_receipt_without_replacing_later_fact(
    fact_review_browser, confirmation_store, tmp_path, surface, operation,
):
    path = "/web/pending?ledger_id=owner&filter=ready" if surface == "drawer" else "/web/expenses/42/edit?ledger_id=owner&return_to=pending&return_filter=ready"
    result = _run_review_page(fact_review_browser, tmp_path, path + f"&probe={operation}", width=1440 if surface == "drawer" else 393)
    assert "error" not in result, result
    assert result["original_preserved"] and result["current_fact"] and result["original_removed"] and result["returned_to_filter"]
    assert len(result["requests"]) == 2 and result["requests"][0] == result["requests"][1]
    assert result["first_receipt"] == (operation == "confirm")
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.amount_cents, current.row_version) == ("后来人工更正", 9900, 9)


def _run_review_page(client, tmp_path, path, *, width=393):
    edge = browser_runtime._discover_edge()
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


def test_unknown_submission_can_inspect_current_pending_record_without_replacing_original_task(fact_review_browser, confirmation_store, tmp_path):
    result = _run_review_page(fact_review_browser, tmp_path, "/web/expenses/42/edit?ledger_id=owner&return_to=pending&probe=pending-current")
    assert "error" not in result, result
    assert result["current_fact"] and result["original_preserved"] and len(result["requests"]) == 1
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.status) == ("首次便利店", 4, "pending")


def test_actual_drawer_retains_input_and_original_save_then_confirms_next_and_last_receipt(review_browser, confirmation_store, tmp_path):
    client, _ = review_browser
    with Session(confirmation_store) as db:
        original = db.get(Expense, 42)
        values = {column.name: getattr(original, column.name) for column in Expense.__table__.columns}
        db.add(Expense(**{**values, "id": 43, "public_id": "next-expense", "merchant": "第二张商家"}))
        db.commit()
    result = _run_review_page(client, tmp_path, "/web/pending?ledger_id=owner&filter=ready", width=1440)
    assert not result.get("error"), json.dumps(result, ensure_ascii=False)
    assert result["first_receipt"] and result["last_receipt"] and result["original_removed"]
    first, replay, confirm_first, confirm_last = result["requests"]
    assert first == replay and first["path"].endswith("/42/save")
    assert confirm_first["path"].endswith("/42/confirm") and confirm_last["path"].endswith("/43/confirm")
    assert result["positions"] == ["第 1 / 2 张", "第 2 / 2 张"]
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).status, db.get(Expense, 42).merchant) == ("confirmed", "抽屉原填写")
        assert db.get(Expense, 43).status == "confirmed"


def test_accepted_drawer_confirmation_with_unavailable_display_only_rereads_the_receipt(review_browser, confirmation_store, tmp_path):
    client, _ = review_browser
    result = _run_review_page(client, tmp_path, "/web/pending?ledger_id=owner&filter=ready&probe=receipt-read-failure")
    assert not result.get("error"), json.dumps(result, ensure_ascii=False)
    assert result["readFailed"] and result["original_removed"]
    assert len(result["requests"]) == 1 and result["requests"][0]["path"].endswith("/42/confirm")
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert current.status == "confirmed" and current.fact_revision == 1


def test_drawer_keeps_unretained_input_when_browser_storage_fails(review_browser, confirmation_store, tmp_path):
    client, _ = review_browser
    result = _run_review_page(client, tmp_path, "/web/pending?ledger_id=owner&probe=storage-failure")
    assert not result.get("error"), json.dumps(result, ensure_ascii=False)
    assert result["storage_recovered"] and not result["requests"]
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).merchant == "首次便利店"


@pytest.mark.parametrize("operation", ["save", "legacy-confirm"])
def test_actual_review_browser_resolves_original_action_before_starting_next_command(
    review_browser, confirmation_store, tmp_path, operation,
):
    client, _ = review_browser
    result = _run_review_page(client, tmp_path, f"/web/expenses/42/edit?ledger_id=owner&return_to=pending&probe={operation}")
    assert not result.get("error"), result
    assert result["original_removed"] and result["receipt_visible"]
    first, replay, *next_command = result["requests"]
    assert first == replay, "Recovery must submit the original action and input, not a fresh confirm"
    assert first["path"].endswith("/save" if operation == "save" else "/confirm")
    if operation == "save":
        assert result["fresh_key"] != dict(first["fields"])["idempotency_key"]
        assert len(next_command) == 1 and next_command[0]["path"].endswith("/confirm")
    else:
        assert not next_command
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert current.status == "confirmed" and current.merchant == "浏览器原填写"


def test_fx_action_checks_original_binding_and_keeps_inputs_and_confirmation_basis(review_browser, confirmation_store, monkeypatch):
    client, scope = review_browser

    def request_fx(db, *, tenant_id, expense_id, expected_row_version, **kwargs):
        current = db.get(Expense, expense_id)
        assert current.row_version == expected_row_version
        current.note, current.row_version = "汇率任务已接受", current.row_version + 1
        db.commit()

    monkeypatch.setattr(_web_expense_fx, "request_pending_expense_fx", request_fx)
    fields = {"ledger_id": "owner", "expected_row_version": "4", "idempotency_key": str(uuid4()),
        "merchant": "未保存的原填写", "amount_yuan": "2850", "original_currency": "JPY", "category": "购物",
        "save_before_confirm": "1", "draft_ref": str(uuid4()), "return_to": "pending",
        "draft_scope": json.dumps({**scope, "deviceId": "previous-browser"})}
    refused = client.post("/web/expenses/42/fx", data=fields)
    assert refused.status_code == 409, refused.text
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).note, db.get(Expense, 42).row_version) == ("", 4)
    fields["draft_scope"] = json.dumps(scope)
    accepted = client.post("/web/expenses/42/fx", data=fields)
    assert accepted.status_code == 200, accepted.text
    assert 'data-page="expense-detail"' in accepted.text
    assert 'value="未保存的原填写"' in accepted.text
    assert 'name="expected_row_version" value="4"' in accepted.text
    assert f'name="idempotency_key" value="{fields["idempotency_key"]}"' in accepted.text
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.status, current.row_version) == ("首次便利店", "pending", 5)


@pytest.mark.parametrize("external_preview", [False, True])
def test_selected_original_requires_confirmation_and_retains_exact_file_after_reload(first_original_web, tmp_path, external_preview):
    case = first_original_web
    sample_bytes = original_tests._camera_jpeg()
    if external_preview:
        import pillow_heif
        from PIL import Image
        encoded = io.BytesIO()
        pillow_heif.from_pillow(Image.open(io.BytesIO(sample_bytes))).save(encoded)
        sample_bytes = encoded.getvalue()
    sample = base64.b64encode(sample_bytes).decode()
    case.client.app.mount("/static", StaticFiles(directory=Path(__file__).parents[1] / "app/static"))
    probe = (Path(__file__).parent / "fixtures/original_selection_probe.js").read_text(encoding="utf-8")

    @case.client.app.middleware("http")
    async def original_selection_probe(request, call_next):
        response = await call_next(request)
        if request.method != "GET" or request.url.path != "/web/expenses/42/original":
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        script = "<script>window.__originalSample=" + json.dumps(sample) + ";window.__externalPreview=" + json.dumps(external_preview) + ";" + probe + "</script>"
        return Response(body.replace(b"</body>", script.encode() + b"</body>"), media_type="text/html")

    before = original_tests._facts(case)
    result = _run_review_page(case.client, tmp_path, "/web/expenses/42/original?ledger_id=owner")
    assert "error" not in result, result
    assert all(result[name] for name in ("decoded", "restored", "explicit_confirmation", "fixed_after_reply_loss"))
    assert original_tests._facts(case) == before
    with Session(case.engine) as db:
        assert len(db.scalars(select(ApiIdempotencyKey)).all()) == 1
        assert db.get(Expense, 42).image_path is not None

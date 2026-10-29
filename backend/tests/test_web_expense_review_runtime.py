"""Actual expense review consumers, commands and receipts with controlled browser identity."""
import asyncio
import base64
import io
import json
import re
from dataclasses import replace
from datetime import timedelta
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError, app_error_handler
from app.middleware.logging import SanitizedLoggingMiddleware
from app.models import ApiIdempotencyKey, Expense
from app.routes import (
    _web_expense_fx,
    _web_expense_helpers,
    expenses,
    web_categories,
    web_duplicates,
    web_expense_create,
    web_expense_lifecycle,
    web_pending,
)
from app.services import (
    category_service,
    expense_review_command_service,
    pending_review_bulk_service,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc
from tests import _web_browser_test_support as browser_runtime
from tests import original_test_support as original_tests
from tests._infra.assets import _camera_jpeg
from tests._web_expense_review_test_support import _run_review_page
from tests._web_expense_review_test_support import fact_review_browser as fact_review_browser
from tests._web_expense_review_test_support import review_browser as review_browser
from tests._web_native_form_support import hidden_post_forms
from tests.web_expense_fact_test_support import confirmation_actor
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store
from tests.web_expense_fact_test_support import confirmation_web as confirmation_web

first_original_web = original_tests.first_original_web


@pytest.mark.real_db
@pytest.mark.parametrize("entry,location,action", [("full", "unlocated", "save"), ("full", "coarse_point", "save"),
    ("drawer", "verified_region", "save"), ("full", "unlocated", "confirm"),
    ("full", "suggested_region", "save"), ("drawer", "suggested_region", "save")])
def test_no_candidate_original_feedback_survives_lost_reply_and_keeps_finance_separate(
        review_browser, confirmation_store, monkeypatch, tmp_path, entry, location, action):
    from PIL import Image, ImageDraw

    from app.models import LedgerLearningEvent, OcrFact
    from app.routes import web_expense_edit, web_expense_lifecycle, web_media
    from app.services.exchange_rate_service import apply_currency_payload
    from app.services.file_service import save_upload_bytes
    from app.services.learning_service import OcrFactDraft, record_ocr_fact
    from app.services.learning_service._source_eligibility import feedback_assessments

    client, _ = review_browser
    image = Image.new("RGB", (400, 800), "white")
    ImageDraw.Draw(image).text((20, 50), "78.00", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    saved = save_upload_bytes(buffer.getvalue(), tenant_id="owner", filename="feedback.png", content_type="image/png")
    with confirmation_store() as db:
        actor = confirmation_actor(db)
        resolve_write_capability(db)
        row = db.get(Expense, 42)
        row.image_path, row.image_hash, row.raw_text = saved.relative_path, saved.image_hash, None
        apply_currency_payload(db, tenant_id="owner", home_currency_code="CNY", expense=row,
            payload=SimpleNamespace(amount_cents=1234), amount_was_explicit=True)
        if location == "suggested_region":
            record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=42, ocr_provider="mock",
                raw_text="实付：7B.OO\n原价：9B.OO", evidence_json=json.dumps({
                    "width": 400, "height": 800, "input_sha256": saved.image_hash,
                    "coordinate_space": "exif-transposed-pixels", "blocks": [
                        {"text": "实付：7B.OO", "box": [[20, 50], [390, 50], [390, 75], [20, 75]]},
                        {"text": "原价：9B.OO", "box": [[20, 100], [390, 100], [390, 125], [20, 125]]}]})))
        db.commit()
    monkeypatch.setattr(web_expense_edit, "resolve_web_actor", lambda *args: (actor.account_id, actor.device_id))
    monkeypatch.setattr(web_expense_lifecycle, "resolve_web_actor", lambda *args: (actor.account_id, actor.device_id))
    client.app.include_router(web_media.router)
    monkeypatch.setattr(web_media, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    client.app.state.expense_review_probe = "original-feedback-probe.js"

    @client.app.get("/original-feedback-probe.js")
    def feedback_probe():
        return FileResponse(Path(__file__).parent / "fixtures/original_feedback_probe.js", media_type="text/javascript")

    cdp = browser_runtime._edge_cdp()
    evaluate = cdp._evaluate_script

    def capture(page, expression):
        result = evaluate(page, expression)
        if action == "confirm" and not result:
            diagnostic = page.request("Runtime.evaluate", {"expression": "JSON.stringify({href:location.href, text:document.body.innerText.slice(-3000),state:sessionStorage.getItem('original-feedback-probe')})", "returnByValue": True})
            (tmp_path / "feedback-confirm-diagnostic.json").write_text(diagnostic.get("result", {}).get("value", "null"), encoding="utf-8")
        preview = page.request("Runtime.evaluate", {"expression": "window.__originalFeedbackPreviewReady && !window.__originalFeedbackPreviewCaptured", "returnByValue": True})
        if preview.get("result", {}).get("value"):
            (tmp_path / "original-feedback.png").write_bytes(base64.b64decode(page.request("Page.captureScreenshot", {"format": "png"})["data"]))
            page.request("Runtime.evaluate", {"expression": "window.__originalFeedbackPreviewCaptured = true"})
        return result

    monkeypatch.setattr(cdp, "_evaluate_script", capture)
    path = "/web/pending?ledger_id=owner&filter=ready" if entry == "drawer" else "/web/expenses/42/edit?ledger_id=owner"
    result = _run_review_page(client, tmp_path, path + "&feedback=" + location + "&feedback_action=" + action, width=1440 if entry == "drawer" else 393)
    (tmp_path / "original-feedback-result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    assert not result.get("error") and result["completed"], result
    assert len(result["requests"]) == 2
    assert dict(result["requests"][0])["idempotency_key"] == dict(result["requests"][1])["idempotency_key"]
    assert dict(result["requests"][0])["original_text_feedback"] == dict(result["requests"][1])["original_text_feedback"]
    with confirmation_store() as db:
        assert db.get(Expense, 42).original_amount_minor == 1700
        assert db.get(Expense, 42).status == ("confirmed" if action == "confirm" else "pending")
        assert len(list(db.scalars(select(OcrFact).where(OcrFact.expense_id == 42)))) == int(location == "suggested_region")
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == 42,
            LedgerLearningEvent.signal_type == "original_text_feedback")))
        assert len(events) == 1
        payload = json.loads(events[0].after_payload)
        assert payload["verbatim_text"] == "实付：78.00" and payload["location_state"] == location
        assert payload["_learning_qualified"] == (location == "verified_region")
        assert feedback_assessments(db, tenant_id="owner", events=events)[events[0].id][0] == (
            "valid" if location == "verified_region" else "needs_review")


@pytest.mark.real_db
@pytest.mark.parametrize("entry,stale,rotated", [("full", False, False), ("drawer", False, True), ("full", True, False)])
def test_candidate_source_review_preserves_draft_and_verifies_original_geometry(
        review_browser, confirmation_store, monkeypatch, tmp_path, entry, stale, rotated):
    from PIL import Image, ImageDraw

    from app.models import LedgerLearningEvent
    from app.routes import web_media
    from app.services.exchange_rate_service import apply_currency_payload
    from app.services.file_service import save_upload_bytes
    from app.services.learning_service import OcrFactDraft, record_ocr_fact
    from tests.test_recognition_source import source_fact

    client, _ = review_browser
    image = Image.new("RGB", (400, 800), "white")
    for y in (40, 80):
        ImageDraw.Draw(image).text((10, y), "49.90", fill="black")
    buffer = io.BytesIO()
    if rotated:
        exif = Image.Exif()
        exif[274] = 6
        image.transpose(Image.Transpose.ROTATE_90).save(buffer, format="JPEG", exif=exif)
    else:
        image.save(buffer, format="PNG")
    saved = save_upload_bytes(buffer.getvalue(), tenant_id="owner", filename="source.jpg" if rotated else "source.png",
        content_type="image/jpeg" if rotated else "image/png")
    fact = source_fact()
    evidence = json.loads(fact.evidence_json)
    evidence["input_sha256"] = "b" * 64 if stale else saved.image_hash
    with confirmation_store() as db:
        resolve_write_capability(db)
        row = db.get(Expense, 42)
        row.image_path, row.image_hash = saved.relative_path, saved.image_hash
        apply_currency_payload(db, tenant_id="owner", home_currency_code="CNY", expense=row,
            payload=SimpleNamespace(amount_cents=1234), amount_was_explicit=True)
        record_ocr_fact(db, OcrFactDraft(tenant_id="owner", expense_id=42, ocr_provider="mock",
            raw_text=fact.raw_text, evidence_json=json.dumps(evidence)))
        db.commit()
    client.app.include_router(web_media.router)
    monkeypatch.setattr(web_media, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    client.app.state.expense_review_probe = "source-review-probe.js"

    @client.app.get("/source-review-probe.js")
    def source_probe():
        return FileResponse(Path(__file__).parent / "fixtures/recognition_source_probe.js", media_type="text/javascript")

    cdp = browser_runtime._edge_cdp()
    evaluate = cdp._evaluate_script

    def capture(page, expression):
        value = evaluate(page, expression)
        preview = page.request("Runtime.evaluate", {"expression": "window.__sourcePreviewReady && !window.__sourcePreviewCaptured", "returnByValue": True})
        if preview.get("result", {}).get("value"):
            (tmp_path / "source-review.png").write_bytes(base64.b64decode(page.request("Page.captureScreenshot", {"format": "png"})["data"]))
            page.request("Runtime.evaluate", {"expression": "window.__sourcePreviewCaptured = true"})
        escape = page.request("Runtime.evaluate", {"expression": "window.__sourceEscapeReady && !window.__sourceEscapeDispatched", "returnByValue": True})
        if escape.get("result", {}).get("value"):
            page.request("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            page.request("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            page.request("Runtime.evaluate", {"expression": "window.__sourceEscapeDispatched = true"})
        return value

    monkeypatch.setattr(cdp, "_evaluate_script", capture)
    path = "/web/pending?ledger_id=owner&filter=ready" if entry == "drawer" else "/web/expenses/42/edit?ledger_id=owner&return_to=pending"
    result = _run_review_page(client, tmp_path, path + ("&stale=1" if stale else ""), width=1440 if entry == "drawer" else 393)
    assert not result.get("error") and result["completed"], result
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        assert (row.original_amount_minor, row.status) == (2200, "confirmed")
        assert not list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == 42,
            LedgerLearningEvent.signal_type.in_(["recognition_field_choice", "recognition_time_choice"]))))


@pytest.mark.real_db
@pytest.mark.parametrize("entry", ["full", "drawer"])
def test_browser_event_choice_preserves_one_transaction_and_replays_without_training_defaults(
        review_browser, confirmation_store, monkeypatch, tmp_path, entry):
    from app.models import LedgerLearningEvent
    from app.routes import web_expense_edit
    from tests.test_recognition_event_drafts import seed_event_material

    client, _ = review_browser
    with confirmation_store() as db:
        resolve_write_capability(db)
        actor = confirmation_actor(db)
        row = db.get(Expense, 42)
        row.original_currency_code = "CNY"
        row.original_amount_minor = row.amount_cents = 1500
        row.image_hash = str(uuid4())
        seed_event_material(db, row)
        db.commit()
    monkeypatch.setattr(web_expense_edit, "resolve_web_actor", lambda *args: (actor.account_id, actor.device_id))
    client.app.state.expense_review_probe = "event-draft-probe.js"

    @client.app.get("/event-draft-probe.js")
    def event_probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_event_draft_probe.js", media_type="text/javascript")

    cdp = browser_runtime._edge_cdp()
    evaluate = cdp._evaluate_script

    def capture(page, expression):
        value = evaluate(page, expression)
        preview = page.request("Runtime.evaluate", {"expression": "window.__eventDraftPreviewReady && !window.__eventDraftPreviewCaptured", "returnByValue": True})
        if preview.get("result", {}).get("value"):
            page.request("Runtime.evaluate", {"expression": """(() => {
                const section = document.querySelector('[data-recognized-fields]');
                if (section) { section.open = true; section.scrollIntoView({block:'start'}); }
            })()"""})
            bounds = page.request("Page.getLayoutMetrics")["cssContentSize"]
            (tmp_path / "event-draft.png").write_bytes(base64.b64decode(page.request("Page.captureScreenshot",
                {"format": "png", "captureBeyondViewport": True, "clip": {**bounds, "scale": 1}})["data"]))
            page.request("Runtime.evaluate", {"expression": "window.__eventDraftPreviewCaptured = true"})
        return value

    monkeypatch.setattr(cdp, "_evaluate_script", capture)
    path = "/web/pending?ledger_id=owner&filter=ready" if entry == "drawer" else "/web/expenses/42/edit?ledger_id=owner&return_to=pending"
    result = _run_review_page(client, tmp_path, path, width=1440 if entry == "drawer" else 393)
    assert not result.get("error") and result["completed"], result
    assert len(result["requests"]) == 2 and result["requests"][0] == result["requests"][1]
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        assert (row.merchant, row.original_amount_minor, row.status) == ("青禾超市", 2800, "pending")
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == 42,
            LedgerLearningEvent.signal_type.in_(["recognition_field_choice", "recognition_time_choice"]))))
        assert len(events) == 3
        assert all(not json.loads(event.after_payload)["_learning_qualified"] for event in events)


@pytest.fixture
def slow_confirmation_script(monkeypatch):
    browser_runtime._discover_database_browser()
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


@pytest.mark.real_db
def test_manual_original_follows_its_creation_receipt_without_losing_file_or_recreating_bill(
    first_original_web, monkeypatch, tmp_path,
):
    """Real native form, creation, receipt and attachment with a controlled browser identity."""
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
    native_statuses = []
    created_locations = []
    viewer_results = []
    with case.session_factory() as db:
        resolve_write_capability(db)
        db.delete(db.get(Expense, 42))
        db.commit()
    create_expense = web_expense_create.create_manual_expense

    def create(db, payload, auth):
        assert payload.amount_cents == 1234 and payload.merchant == "原稿商家" and auth == case.original_auth
        assert not creations, "The original creation must not be posted again to transfer its file"
        receipt = create_expense(db, payload, auth)
        creations.append((payload.client_ref, receipt.id, receipt.row_version))
        return receipt

    monkeypatch.setattr(web_expense_create, "create_manual_expense", create)
    sample = base64.b64encode(_camera_jpeg()).decode()
    probe = (Path(__file__).parent / "fixtures/manual_original_probe.js").read_text(encoding="utf-8")

    @case.client.app.middleware("http")
    async def manual_original_probe(request, call_next):
        native_post = request.method == "POST" and request.url.path == "/web/expenses/new"
        if native_post and native_statuses == [422]:
            case.auth = replace(case.original_auth, role="viewer")
            case.options[0].role = "viewer"
        response = await call_next(request)
        if native_post:
            native_statuses.append(response.status_code)
            if response.status_code == 303:
                created_locations.append(response.headers["location"])
        if request.url.path == "/web/expenses/new/result" and case.auth.role == "viewer":
            viewer_results.append(response.status_code)
            assert not creations
            with case.session_factory() as db:
                assert db.scalar(select(Expense.id)) is None
            # Another member restores the role after this read-only result lookup.
            # The original form must still get fresh server admission before retry.
            case.auth = case.original_auth
            case.options[0].role = "owner"
        if "text/html" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        script = "<script>window.__originalSample=" + json.dumps(sample) + ";" + probe + "</script>"
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(body.replace(b"</body>", script.encode() + b"</body>"), status_code=response.status_code, headers=headers)

    result = _run_review_page(case.client, tmp_path, "/web/expenses/new?ledger_id=owner&return_to=confirmed"
        "&return_month=2026-08&return_page=3&return_query=原稿&return_category=餐饮&return_tag=重要&return_home_currency_code=JPY")
    assert "error" not in result, result
    assert result["rejected_preserved"] and result["transfer_retried"] and result["explicit_original_confirmation"]
    assert result["permission_restored"] and native_statuses == [422, 403, 303] and viewer_results == [200]
    redirect_query = parse_qs(urlsplit(created_locations[0]).query)
    assert all(redirect_query.get(name) == [value] for name, value in result["origin"])
    assert len(creations) == 1 and creations[0][0] == result["ref"]
    _, created_id, created_version = creations[0]
    with case.session_factory() as db:
        assert len(db.scalars(select(Expense)).all()) == 1
        row = db.get(Expense, created_id)
        assert (row.merchant, row.amount_cents, row.row_version) == ("原稿商家", 1234, created_version + 1)
        assert row.image_path and row.image_hash
        receipts = db.scalars(select(ApiIdempotencyKey)).all()
        assert len(receipts) == 2
        original = next(r for r in receipts if r.operation == "attach_original")
        assert original.idempotency_key == result["ref"] and original.response_body["sha256"] == row.image_hash


@pytest.mark.real_db
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
    with case.session_factory() as db:
        resolve_write_capability(db)
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
    with case.session_factory() as db:
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

    with confirmation_store() as db:
        resolve_write_capability(db)
        row = db.get(Expense, 42)
        row.category = ""
        for identity, category, status, tenant in [(43, "其他", "pending", "owner"),
            (44, "未分类", "pending", "owner"), (45, "", "confirmed", "owner"),
            (46, "", "pending", "tester_1")]:
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
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        row.category, row.row_version = "医疗", 5
        db.commit()
    result = client.post("/web/categories/uncategorized/bulk-set", data={"ledger_id": "owner",
        "draft_scope": json.dumps(scope), "idempotency_key": str(uuid4()), "expense_ids": ["42"], "expected_row_version": ["4"],
        "category": "购物"}, follow_redirects=False)
    with confirmation_store() as db:
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
    with confirmation_store() as db:
        row = db.get(Expense, 44)
        row.category, row.row_version = "交通", 5
        db.commit()
    result = client.post("/web/categories/uncategorized/bulk-set", data={"ledger_id": "owner",
        "draft_scope": json.dumps(scope), "idempotency_key": str(uuid4()), "expense_snapshot": ["42:4", "44:4"], "category": "自选分类"}, follow_redirects=False)
    assert "已更新 1 条" in result.text and "跳过 1 条" in result.text
    assert "刷新后重新选择" not in result.text
    assert re.search(r'name="expense_snapshot" value="44:4"[^>]*checked', result.text)
    assert "自选分类" in result.text and 'aria-label="继续逐笔核对"' in result.text
    with confirmation_store() as db:
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
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        row.category, row.row_version = "医疗", 8
        db.commit()
    replay = client.post("/web/categories/uncategorized/bulk-set", data=original)
    assert "已更新 2 条" in replay.text, "The first accepted batch must survive response loss and later edits"
    with confirmation_store() as db:
        assert (db.get(Expense, 42).category, db.get(Expense, 42).row_version) == ("医疗", 8)
        assert (db.get(Expense, 44).category, db.get(Expense, 44).row_version) == ("购物", 5)
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == original["idempotency_key"]))


@pytest.mark.real_db
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
        with confirmation_store() as db:
            resolve_write_capability(db)
            row = db.get(Expense, 44 if stage == "before" else 42)
            row.category, row.row_version = ("交通", 8) if stage == "before" else ("医疗", 9)
            db.commit()
        return {"changed": True}

    result = _run_review_page(client, tmp_path, "/web/categories/uncategorized?ledger_id=owner")
    assert "error" not in result, result
    assert result["detail_return"] and result["original_restored"] and result["partial_continued"]
    first, replay, final = result["requests"]
    assert first == replay and final != first
    with confirmation_store() as db:
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
    with confirmation_store() as db:
        assert db.get(Expense, 42).category == ""
        assert (db.get(Expense, 44).category, db.get(Expense, 44).row_version) == ("未分类", 4)
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == original["idempotency_key"])) is None


@pytest.fixture
def related_review_browser(review_browser, confirmation_store, monkeypatch):
    client, _ = review_browser
    options = [SimpleNamespace(ledger_id="owner", name="家庭账本", role="owner", is_default=True)]

    client.app.include_router(web_duplicates.router)
    monkeypatch.setattr(web_duplicates, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_duplicates, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")

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
        with confirmation_store() as db:
            row = db.get(Expense, 42)
            row.status, row.rejected_at = "rejected", now_utc()
            db.commit()
    path = f"/web/{'duplicates' if action.startswith('reject-') else 'expenses'}/42/{action}"
    response = related_review_browser.post(path, data=fields, follow_redirects=False)
    assert response.status_code == 409, response.text
    assert 'name="draft_scope"' in response.text
    refused = related_review_browser.post(path, data=fields, headers={"Accept": "application/json"})
    assert refused.status_code == 409 and refused.json()["draft_result"] == "blocked"
    assert "ack" not in refused.json()
    with confirmation_store() as db:
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
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        assert (row.status, row.merchant, row.row_version) == ("pending", "首次便利店", 4)


@pytest.mark.parametrize("action", ["reject", "undo"])
def test_ignore_or_undo_replay_recognizes_original_after_later_confirmation(
    related_review_browser, confirmation_store, action,
):
    fields = _related_keep_fields()
    if action == "undo":
        with confirmation_store() as db:
            row = db.get(Expense, 42)
            row.status, row.rejected_at = "rejected", now_utc()
            db.commit()
    path = f"/web/expenses/42/{action}"
    first = related_review_browser.post(path, data=fields, follow_redirects=False)
    assert first.status_code == 303, first.text
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        row.status, row.row_version, row.merchant = "confirmed", 9, "后来入账"
        db.commit()
    replay = related_review_browser.post(path, data=fields, follow_redirects=False)
    assert replay.status_code == 303, replay.text
    receipt = related_review_browser.post(path, data=fields, headers={"Accept": "application/json"}).json()
    assert (receipt["receipt"]["status"], receipt["receipt"]["row_version"]) == ("rejected" if action == "reject" else "pending", 5)
    assert receipt["ack"]["clientRef"] == fields["reject_idempotency_key" if action == "reject" else "idempotency_key"]
    with confirmation_store() as db:
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
    with confirmation_store() as db:
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
    with confirmation_store() as db:
        db.get(Expense, 42).row_version = 9
        db.commit()
    reopened = related_review_browser.get(first.headers["location"])
    assert '/web/expenses/42/undo' not in hidden_post_forms(reopened.text), "original banner retargeted a later ignore"
    task = related_review_browser.get(f'/web/expenses/42/undo?ledger_id=owner&undo_version=5&undo_key={original["idempotency_key"]}')
    resumed = hidden_post_forms(task.text)["/web/expenses/42/undo"]
    assert (resumed["expected_row_version"], resumed["idempotency_key"]) == ("5", original["idempotency_key"])
    refused = related_review_browser.post("/web/expenses/42/undo", data=resumed, headers={"Accept": "application/json"})
    assert refused.status_code == 404 and refused.json()["error"] == "expense_not_found"
    assert refused.json()["draft_result"] == "blocked"
    with confirmation_store() as db:
        assert (db.get(Expense, 42).row_version, db.get(Expense, 42).status) == (9, "rejected")


@pytest.mark.real_db
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
        with confirmation_store() as db:
            resolve_write_capability(db)
            row = db.get(Expense, 42)
            assert (row.status, row.row_version) == ("pending", 6)
            row.status, row.row_version, row.merchant = "rejected", 9, "同伴后来再次忽略"
            db.commit()
        return {"changed": True}

    @client.app.get("/ignore-current")
    def current():
        with confirmation_store() as db:
            row = db.get(Expense, 42)
            return {"version": row.row_version, "status": row.status, "merchant": row.merchant}

    client.app.state.expense_review_probe = "ignore-recovery-probe.js"
    path = "/web/pending?ledger_id=owner&filter=ready" if entry == "drawer" else "/web/expenses/42/edit?ledger_id=owner&return_to=pending&return_filter=ready"
    result = _run_review_page(client, tmp_path, path + f"&entry={entry}&later={int(later_ignore)}", width=1440)
    assert "error" not in result, json.dumps(result, ensure_ascii=False)
    assert result["financial_retained"] and result["reject_lost"] and result["undo_lost"]
    assert result["requests"]["reject"][0] == result["requests"]["reject"][1]
    assert result["requests"]["undo"][0] == result["requests"]["undo"][1]
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        assert (row.status, row.merchant) == (("rejected", "同伴后来再次忽略") if later_ignore else ("confirmed", "忽略前的原填写"))


def test_duplicate_review_keeps_both_originals_currency_and_group_return(related_review_browser, fact_review_browser, confirmation_store):
    client = related_review_browser
    with confirmation_store() as db:
        resolve_write_capability(db)
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
            db.flush()
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
    with confirmation_store() as db:
        kept = db.get(Expense, 42)
        assert (kept.status, kept.duplicate_status, kept.duplicate_of_id) == ("pending", "suspected", 44)
        assert db.get(Expense, 43).status == "confirmed"
        assert db.get(Expense, 44).duplicate_status == "suspected"


@pytest.mark.real_db
@pytest.mark.parametrize("entry,fault", [("drawer", "reply"), ("full", "reply"), ("drawer", "ack-store"), ("drawer", "rejected")])
def test_keep_original_survives_reload_then_rejoins_financial_draft(related_review_browser, confirmation_store, tmp_path, entry, fault):
    client = related_review_browser
    with confirmation_store() as db:
        resolve_write_capability(db)
        db.get(Expense, 42).duplicate_status = "suspected"
        db.commit()

    @client.app.get("/keep-recovery-probe.js")
    def recovery_probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_keep_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/keep-later")
    def later():
        with confirmation_store() as db:
            resolve_write_capability(db)
            row = db.get(Expense, 42)
            row.row_version, row.merchant = 9, "后来填写"
            row.duplicate_status = "none" if (entry, fault) == ("drawer", "reply") else "suspected"
            db.commit()
        return {"changed": True}

    @client.app.get("/keep-current")
    def current():
        with confirmation_store() as db:
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
    with confirmation_store() as db:
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
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        assert (row.status, row.merchant, row.row_version) == ("pending", "首次便利店", 5)


def test_related_keep_replay_recognizes_original_decision_without_overwriting_later_state(related_review_browser, confirmation_store, monkeypatch):
    fields = {**_related_keep_fields(), "fragment": "1"}
    assert related_review_browser.post("/web/duplicates/42/keep", data=fields).status_code == 200
    with confirmation_store() as db:
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
    with confirmation_store() as db:
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
    with confirmation_store() as db:
        assert db.get(Expense, 42).row_version == 4


@pytest.mark.parametrize("action", ["keep", "reject-current", "reject-original"])
def test_standalone_duplicate_form_carries_its_original_decision_and_browser_identity(related_review_browser, confirmation_store, action):
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        db.add(Expense(**{column.name: getattr(current, column.name) for column in Expense.__table__.columns
            if column.name not in {"id", "public_id"}}, id=43, public_id="comparison-expense"))
        db.flush()
        current.duplicate_status, current.duplicate_of_id = "suspected", 43
        db.commit()
    page = related_review_browser.get("/web/duplicates?ledger_id=owner")
    path = f"/web/duplicates/42/{action}"
    fields = hidden_post_forms(page.text)[path]
    key = fields["idempotency_key"]
    assert json.loads(fields["draft_scope"])["deviceId"] == "browser"
    response = related_review_browser.post(path, data=fields, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/web/duplicates?")
    with confirmation_store() as db:
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
    with confirmation_store() as db:
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
    with confirmation_store() as db:
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
    with confirmation_store() as db:
        assert db.get(Expense, 42).row_version == 4
        assert db.scalar(select(ApiIdempotencyKey)) is None


@pytest.mark.real_db
@pytest.mark.parametrize("action,fault", [("keep", "reply"), ("reject-current", "reply"), ("reject-original", "reply"), ("keep", "conflict")])
def test_standalone_decision_recovers_original_or_explicitly_reviews_a_refusal(
    related_review_browser, confirmation_store, tmp_path, action, fault, slow_confirmation_script,
):
    client = related_review_browser
    with confirmation_store() as db:
        resolve_write_capability(db)
        row = db.get(Expense, 42)
        db.add(Expense(**{c.name: getattr(row, c.name) for c in Expense.__table__.columns
            if c.name not in {"id", "public_id"}}, id=43, public_id="original-comparison"))
        db.flush()
        row.duplicate_status, row.duplicate_of_id = "suspected", 43
        db.commit()

    @client.app.get("/duplicate-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/duplicate_decision_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/duplicate-peer")
    def peer():
        with confirmation_store() as db:
            resolve_write_capability(db)
            current, original = db.get(Expense, 42), db.get(Expense, 43)
            current.merchant, current.row_version, current.duplicate_status = "后来修改本次", 9, "suspected"
            original.merchant, original.row_version, original.status = "后来修改参考", 11, "confirmed"
            db.commit()
        return {"changed": True}

    @client.app.get("/duplicate-facts")
    def facts():
        with confirmation_store() as db:
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
    client.app.dependency_overrides[expenses.get_current_writer_context] = lambda: SimpleNamespace(tenant_id="owner", device_id=None, account_id=None)
    monkeypatch.setattr(expenses, "expense_to_response", expense_review_command_service.expense_to_response)
    fields = {**_related_keep_fields(), "fragment": "1"}

    def submit(surface):
        if surface == "web":
            return client.post("/web/duplicates/42/keep", data=fields)
        return client.post("/api/expenses/42/mark-not-duplicate", json={"expected_row_version": 4},
            headers={"Idempotency-Key": fields["keep_idempotency_key"]})

    first = submit(first_surface)
    assert first.status_code == 200, first.text
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        row.duplicate_status, row.row_version = "suspected", 9
        db.commit()
    replay = submit("web" if first_surface == "api" else "api")
    assert replay.status_code == 200, replay.text
    with confirmation_store() as db:
        assert (db.get(Expense, 42).duplicate_status, db.get(Expense, 42).row_version) == ("suspected", 9)
        assert [(r.operation, r.status) for r in db.scalars(select(ApiIdempotencyKey))] == [("mark_not_duplicate", "succeeded")]


def test_keep_decision_and_idempotency_record_roll_back_together(related_review_browser, confirmation_store, monkeypatch):
    def fail(*args, **kwargs):
        raise SQLAlchemyError("decision persistence failed")

    monkeypatch.setattr(expense_review_command_service, "mark_idempotency_succeeded", fail)
    with confirmation_store() as db, pytest.raises(SQLAlchemyError, match="decision persistence failed"):
        expense_review_command_service.submit_expense_duplicate_decision(db, tenant_id="owner", expense_id=42,
            expected_row_version=4, request_expected_row_version=4, idempotency_key=str(uuid4()))
    with confirmation_store() as db:
        assert db.get(Expense, 42).row_version == 4
        assert db.scalar(select(ApiIdempotencyKey)) is None


@pytest.mark.real_db
@pytest.mark.parametrize("action,entry", [("keep", "drawer"), ("reject", "drawer"), ("keep", "full")])
def test_related_review_actions_keep_input_and_rejoin_original_queue_before_confirmation(
    related_review_browser, confirmation_store, tmp_path, action, entry,
):
    if action == "keep":
        with confirmation_store() as db:
            resolve_write_capability(db)
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
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.status, current.merchant, current.amount_cents) == ("confirmed", "相关操作前的填写", 12860)


@pytest.mark.real_db
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
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.amount_cents, current.row_version) == ("后来人工更正", 9900, 9)


@pytest.mark.real_db
def test_unknown_submission_can_inspect_current_pending_record_without_replacing_original_task(fact_review_browser, confirmation_store, tmp_path):
    result = _run_review_page(fact_review_browser, tmp_path, "/web/expenses/42/edit?ledger_id=owner&return_to=pending&probe=pending-current")
    assert "error" not in result, result
    assert result["current_fact"] and result["original_preserved"] and len(result["requests"]) == 1
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.status) == ("首次便利店", 4, "pending")


@pytest.mark.real_db
def test_actual_drawer_retains_input_and_original_save_then_confirms_next_and_last_receipt(review_browser, confirmation_store, tmp_path):
    client, _ = review_browser
    with confirmation_store() as db:
        resolve_write_capability(db)
        original = db.get(Expense, 42)
        values = {column.name: getattr(original, column.name) for column in Expense.__table__.columns}
        db.add(Expense(**{**values, "id": 43, "public_id": "next-expense", "merchant": "第二张商家",
            "created_at": original.created_at - timedelta(seconds=1)}))
        db.commit()
    result = _run_review_page(client, tmp_path, "/web/pending?ledger_id=owner&filter=ready", width=1440)
    assert not result.get("error"), json.dumps(result, ensure_ascii=False)
    assert result["first_receipt"] and result["last_receipt"] and result["original_removed"]
    first, replay, confirm_first, confirm_last = result["requests"]
    assert first == replay and first["path"].endswith("/42/save")
    assert confirm_first["path"].endswith("/42/confirm") and confirm_last["path"].endswith("/43/confirm")
    assert result["positions"] == ["第 1 / 2 张", "第 2 / 2 张"]
    with confirmation_store() as db:
        assert (db.get(Expense, 42).status, db.get(Expense, 42).merchant) == ("confirmed", "抽屉原填写")
        assert db.get(Expense, 43).status == "confirmed"


@pytest.mark.real_db
def test_accepted_drawer_confirmation_with_unavailable_display_only_rereads_the_receipt(review_browser, confirmation_store, tmp_path):
    client, _ = review_browser
    result = _run_review_page(client, tmp_path, "/web/pending?ledger_id=owner&filter=ready&probe=receipt-read-failure")
    assert not result.get("error"), json.dumps(result, ensure_ascii=False)
    assert result["readFailed"] and result["original_removed"]
    assert len(result["requests"]) == 1 and result["requests"][0]["path"].endswith("/42/confirm")
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert current.status == "confirmed" and current.fact_revision == 1


@pytest.mark.real_db
def test_drawer_keeps_unretained_input_when_browser_storage_fails(review_browser, confirmation_store, tmp_path):
    client, _ = review_browser
    result = _run_review_page(client, tmp_path, "/web/pending?ledger_id=owner&probe=storage-failure")
    assert not result.get("error"), json.dumps(result, ensure_ascii=False)
    assert result["storage_recovered"] and not result["requests"]
    with confirmation_store() as db:
        assert db.get(Expense, 42).merchant == "首次便利店"


@pytest.mark.real_db
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
        assert not {"value_score", "regret_score"}.intersection(dict(first["fields"]))
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert current.status == "confirmed" and current.merchant == "浏览器原填写"


@pytest.mark.real_db
@pytest.mark.parametrize("year_completion,single_use,field_choice", [(False, False, False), (True, False, False),
    (False, True, False), (False, False, True), (False, False, "original_correction"), (False, False, "notification")])
def test_browser_explicit_same_category_replays_original_advice_once(review_browser, confirmation_store, monkeypatch, tmp_path, year_completion, single_use, field_choice):
    from app.models import AlgorithmDecision, LedgerLearningEvent
    from app.routes import web_expense_edit
    from app.services.expense_accounting_time_service import refresh_legacy_expense_time
    from app.services.pending_suggestion_service import record_category_choice

    client, _ = review_browser
    with confirmation_store() as db:
        actor = confirmation_actor(db)
        original = db.get(Expense, 42)
        financial = (original.amount_cents, original.original_amount_minor, original.original_currency_code, original.status)
    monkeypatch.setattr(web_expense_edit, "resolve_web_actor", lambda *args: (actor.account_id, actor.device_id))
    with confirmation_store() as db:
        resolve_write_capability(db)
        _seed_review_field_evidence(db, actor, year_completion, field_choice)
        for _ in range(3):
            previous = Expense(tenant_id="owner", merchant="首次便利店", category="购物", amount_cents=1000,
                original_amount_minor=1000, original_currency_code=original.original_currency_code,
                home_currency_code=original.home_currency_code, note=original.note, tags=original.tags,
                source="pytest", raw_text="", status="confirmed", confirmed_at=now_utc()-timedelta(days=1),
                expense_time=now_utc()-timedelta(days=1))
            refresh_legacy_expense_time(db, previous)
            db.add(previous)
            db.flush()
            record_category_choice(db, expense=previous, previous_category="其他",
                previous_merchant=previous.merchant, actor_account_id=actor.account_id, choice="manual")
        db.commit()
    client.app.state.expense_review_probe = "learning-choice-probe.js"

    @client.app.get("/learning-choice-probe.js")
    def learning_probe():
        probe = (Path(__file__).parent / "fixtures/expense_learning_choice_probe.js").read_text(encoding="utf-8")
        flags = "window.__categorySingleUse=" + json.dumps(single_use) + ";window.__fieldChoice=" + json.dumps(field_choice) + ";"
        return Response(flags + probe, media_type="text/javascript")

    cdp = browser_runtime._edge_cdp()
    evaluate = cdp._evaluate_script

    def capture(page, expression):
        value = evaluate(page, expression)
        if value.get("type") != "undefined":
            page.request("Runtime.evaluate", {"expression": """(() => {
                const target = document.querySelector('[data-recognized-field]') || document.querySelector('[data-recognized-year]') || document.querySelector('[data-learning-suggestion]');
                if (!target) return;
                for (let parent = target.parentElement; parent; parent = parent.parentElement) {
                    if (parent.tagName === 'DETAILS' && !parent.open) parent.querySelector(':scope > summary').click();
                }
                target.scrollIntoView({block:'center'});
            })()"""})
            (tmp_path / "learning-choice.png").write_bytes(base64.b64decode(page.request("Page.captureScreenshot", {"format": "png"})["data"]))
        return value

    monkeypatch.setattr(cdp, "_evaluate_script", capture)
    result = _run_review_page(client, tmp_path, "/web/expenses/42/edit?ledger_id=owner&return_to=pending")
    assert not result.get("error") and result["completed"], result
    assert len(result["requests"]) == 2 and result["requests"][0] == result["requests"][1]
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.amount_cents, current.original_amount_minor, current.original_currency_code, current.status) == financial
        events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.subject_id == 42)))
        assert len(events) == (4 if field_choice else 2)
        _assert_replayed_source_choices(events, actor, current, result, field_choice, year_completion)
        event = next(row for row in events if row.signal_type == "category_suggestion")
        assert event.event_type == "accept" and event.actor_account_id == actor.account_id
        assert json.loads(event.after_payload)["_category_intent"] == ("one_off" if single_use else "suggestion")
        assert db.get(AlgorithmDecision, event.decision_id).public_id == result["decision"]


def _seed_review_field_evidence(db, actor, year_completion, field_choice):
    from app.models import PaymentCapture
    from app.schemas.notification_fields import NotificationFieldEvidence
    from app.services.expense_service._ocr_facts import append_ocr_fact
    from app.services.notification_field_service import freeze_notification_fields
    from app.services.ocr_service import OcrResult

    text = "支付时间：02月29日23:04:05 +07:00" if year_completion else "支付时间：2026-10-18 12:20"
    if field_choice == "notification":
        evidence = NotificationFieldEvidence(fragments=[{"field": "text", "literal": "商户：首次便利店"},
            {"field": "text", "literal": "支付金额：JPY 2850"}])
        db.add(PaymentCapture(tenant_id="owner", actor_account_id=actor.account_id, source="alipay",
            captured_at=now_utc(), original_currency="JPY", original_amount_minor=2850,
            merchant="首次便利店", parser_version="transaction-evidence-v4", candidates=[],
            kind="expense", expense_public_id=db.get(Expense, 42).public_id, created_at=now_utc(),
            field_evidence=freeze_notification_fields(evidence, "JPY")))
    elif field_choice:
        text = ("商户：首识便利店\n支付金额：JPY 28500\n" if field_choice == "original_correction"
            else "商户：首次便利店\n支付金额：JPY 2850\n") + text
    append_ocr_fact(db, expense=db.get(Expense, 42), provider_name="mock", timezone_name="Asia/Shanghai",
        result=OcrResult(raw_text=text, confidence=0.9))


def _assert_replayed_source_choices(events, actor, current, result, field_choice, year_completion):
    if field_choice:
        _assert_replayed_field_choices(events, actor, result, field_choice)
    time_event = next(row for row in events if row.signal_type == "recognition_time_choice")
    assert time_event.event_type == ("edit" if year_completion else "accept") and time_event.actor_account_id == actor.account_id
    assert json.loads(time_event.after_payload)["candidate_id"] == json.loads(result["timeChoice"])["candidate_id"]
    if year_completion:
        payload = json.loads(time_event.after_payload)
        assert payload["intent"] == "original_correction" and payload["modified_components"] == ["year"]
        assert current.expense_time.isoformat() == "2024-02-29T16:04:05+00:00"


def _assert_replayed_field_choices(events, actor, result, field_choice):
    field_events = [row for row in events if row.signal_type == "recognition_field_choice"]
    assert {json.loads(row.after_payload)["field"] for row in field_events} == {"amount_cents", "merchant"}
    expected_type = "edit" if field_choice == "original_correction" else "accept"
    assert all(row.actor_account_id == actor.account_id and row.event_type == expected_type for row in field_events)
    assert all(json.loads(row.after_payload)["_learning_qualified"] for row in field_events)
    if field_choice == "notification":
        assert all(json.loads(row.after_payload)["source"] == "notification" for row in field_events)
    assert {json.loads(row.after_payload)["candidate_id"] for row in field_events} == {
        row["candidate_id"] for row in json.loads(result["fieldChoices"])}


@pytest.mark.real_db
@pytest.mark.parametrize("drawer", [False, True])
def test_explicit_latest_bill_load_uses_current_fields_while_retaining_original_task(
    review_browser, confirmation_store, monkeypatch, tmp_path, drawer,
):
    client, _ = review_browser
    monkeypatch.setattr(_web_expense_helpers, "expense_fx_view", lambda *a, **k: {
        "state": "completed", "can_request": False, "current": {"original_currency_code": "CNY"}})
    client.app.state.expense_review_probe = "latest-review-probe.js"
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        money_before = (row.amount_cents, row.original_amount_minor, row.original_currency_code, row.status)

    @client.app.get("/latest-review-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_review_latest_probe.js", media_type="text/javascript")

    @client.app.get("/web/latest-review-probe")
    def driver():
        return Response('<html><head><meta charset="utf-8"></head><body></body></html>', media_type="text/html")

    @client.app.post("/probe-latest-bill")
    def current_bill():
        with confirmation_store() as db:
            resolve_write_capability(db)
            row = db.get(Expense, 42)
            row.row_version, row.merchant = 5, "服务器当前商家"
            db.commit()
        return {"changed": True}

    result = _run_review_page(client, tmp_path, f"/web/latest-review-probe?drawer={str(drawer).lower()}", width=1440 if drawer else 393)
    assert not result["error"], result
    assert result["before"]["amount_yuan"] == "29.00" and result["before"]["expected_row_version"] == "4"
    assert result["after"]["amount_yuan"] == result["saved"]["amount_yuan"]
    assert result["after"]["merchant"] == "服务器当前商家" and result["after"]["expected_row_version"] == "5"
    assert result["after"]["draft_ref"] != result["saved"]["draft_ref"]
    assert result["retained"]["values"]["amount_yuan"] == "29.00"
    assert result["retained"]["values"]["expected_row_version"] == "4"
    with confirmation_store() as db:
        row = db.get(Expense, 42)
        assert row.row_version == 5 and row.merchant == "服务器当前商家"
        assert (row.amount_cents, row.original_amount_minor, row.original_currency_code, row.status) == money_before
        assert not db.scalars(select(ApiIdempotencyKey)).all()


def test_fx_action_checks_original_binding_and_keeps_inputs_and_confirmation_basis(review_browser, confirmation_store, monkeypatch):
    client, scope = review_browser
    requests = []

    def request_fx(db, *, tenant_id, expense_id, expected_row_version, **kwargs):
        requests.append((tenant_id, expense_id, expected_row_version, kwargs))

    monkeypatch.setattr(_web_expense_fx, "request_pending_expense_fx", request_fx)
    fields = {"ledger_id": "owner", "expected_row_version": "4", "idempotency_key": str(uuid4()),
        "merchant": "未保存的原填写", "amount_yuan": "2850", "original_currency": "JPY", "category": "购物",
        "save_before_confirm": "1", "draft_ref": str(uuid4()), "return_to": "pending", "value_score": "", "regret_score": "5",
        "draft_scope": json.dumps({**scope, "deviceId": "previous-browser"})}
    refused = client.post("/web/expenses/42/fx", data=fields)
    assert refused.status_code == 409, refused.text
    assert not requests
    with confirmation_store() as db:
        assert (db.get(Expense, 42).note, db.get(Expense, 42).row_version) == ("", 4)
    fields["draft_scope"] = json.dumps(scope)
    accepted = client.post("/web/expenses/42/fx", data=fields)
    assert accepted.status_code == 200, accepted.text
    assert 'data-page="expense-detail"' in accepted.text
    assert 'value="未保存的原填写"' in accepted.text
    assert 'name="expected_row_version" value="4"' in accepted.text
    assert f'name="idempotency_key" value="{fields["idempotency_key"]}"' in accepted.text
    for name, value in (("value_score", ""), ("regret_score", "5")):
        assert re.search(rf'name="{name}" value="{value}"\s+checked', accepted.text)
    with confirmation_store() as db:
        auth = confirmation_actor(db)
        current = db.get(Expense, 42)
        assert (current.merchant, current.status, current.row_version) == ("首次便利店", "pending", 4)
        assert requests == [("owner", 42, 4, {
            "initiator_account_id": auth.account_id, "initiator_device_id": auth.device_id})]


@pytest.mark.real_db
@pytest.mark.parametrize("external_preview", [False, True])
def test_selected_original_requires_confirmation_and_retains_exact_file_after_reload(first_original_web, tmp_path, external_preview):
    case = first_original_web
    sample_bytes = _camera_jpeg()
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
        from app.middleware.security_headers import _CSP
        # Keep the shipped image policy while allowing this fixture's inline journey probe.
        image_policy = next(part.strip() for part in _CSP.split(";") if part.strip().startswith("img-src "))
        return Response(body.replace(b"</body>", script.encode() + b"</body>"), media_type="text/html",
                        headers={"Content-Security-Policy": image_policy})

    before = original_tests._facts(case)
    result = _run_review_page(case.client, tmp_path, "/web/expenses/42/original?ledger_id=owner")
    assert "error" not in result, result
    assert all(result[name] for name in ("decoded", "restored", "explicit_confirmation", "fixed_after_reply_loss"))
    assert original_tests._facts(case) == before
    with case.session_factory() as db:
        assert len(db.scalars(select(ApiIdempotencyKey)).all()) == 1
        assert db.get(Expense, 42).image_path is not None

"""Actual recognition pages retain independent intent and acknowledge only its original command."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.middleware.logging import SanitizedLoggingMiddleware
from app.models import ApiIdempotencyKey, Expense, OcrFact
from app.routes import web_expense_recognition
from app.services import expense_ocr_command_service as command
from app.services import expense_ocr_task_service as ocr_tasks
from app.services.background_task_worker import run_task
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_service import _ocr
from app.services.ocr_service import OcrResult
from tests import _web_expense_review_test_support as review_tests
from tests._web_native_form_support import hidden_post_forms
from tests.web_expense_fact_test_support import confirmation_actor
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store
from tests.web_expense_fact_test_support import confirmation_web as confirmation_web

pytestmark = pytest.mark.real_db

review_browser = review_tests.review_browser


@pytest.fixture
def recognition_browser(review_browser, confirmation_store, monkeypatch):
    client, scope = review_browser
    options = [SimpleNamespace(ledger_id="owner", name="家庭账本", role="owner", is_default=True)]
    client.app.include_router(web_expense_recognition.router)
    monkeypatch.setattr(web_expense_recognition, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_expense_recognition, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    with confirmation_store() as db:
        actor = confirmation_actor(db)
    monkeypatch.setattr(web_expense_recognition, "resolve_web_actor", lambda *args: (actor.account_id, actor.device_id))
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")
    accepted = []
    monkeypatch.setattr(_ocr, "_active_provider_name", lambda: "mock")
    monkeypatch.setattr(_ocr, "extract_ocr_result", lambda expense: OcrResult(
        raw_text="中国建设银行\n交易金额：18.51", confidence=0.9, amount_cents=1851, merchant="中国建设银行"))
    extract = _ocr.extract_explicit_ocr

    def capture_image(expense, timezone_name):
        result = extract(expense, timezone_name)
        accepted.append(expense.id)
        return result

    monkeypatch.setattr(_ocr, "extract_explicit_ocr", capture_image)
    for name in ("recognize_expense_text",):
        operation = getattr(command, name)

        def capture(db, expense_id, *args, _operation=operation, **kwargs):
            result = _operation(db, expense_id, *args, **kwargs)
            accepted.append(expense_id)
            return result

        monkeypatch.setattr(command, name, capture)
    with confirmation_store() as db:
        resolve_write_capability(db)
        db.get(Expense, 42).image_path = "controlled-original.png"
        db.commit()

    @client.app.get("/recognition-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/recognition_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/recognition-later-fact")
    def later_fact():
        with confirmation_store() as db:
            resolve_write_capability(db)
            current = db.get(Expense, 42)
            current.merchant, current.row_version = "后来人工核对", 12
            db.commit()
        return {"changed": True}

    client.app.state.expense_review_probe = "recognition-probe.js"
    return client, scope, options, accepted


def _fields(client, path):
    page = client.get(path + "?ledger_id=owner&return_to=pending&return_filter=ready")
    assert page.status_code == 200, page.text
    fields = hidden_post_forms(page.text)[path]
    if path.endswith("recognize-text"):
        fields["raw_text"] = "中国建设银行\n交易金额：18.51\n原粘贴文字"
    return fields


@pytest.mark.parametrize("suffix", ["recognize-text", "ocr/retry"])
def test_recognition_acknowledges_original_request_without_overwriting_later_facts(recognition_browser, confirmation_store, suffix):
    client, scope, _, accepted = recognition_browser
    path = "/web/expenses/42/" + suffix
    fields = _fields(client, path)
    first = client.post(path, data=fields, headers={"Accept": "application/json"})
    assert first.status_code == 200, first.text
    assert first.json()["ack"] == {"scope": scope, "clientRef": fields["idempotency_key"]}
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.status, current.fact_revision) == ("首次便利店", 5, "pending", 0)
        suggestion = db.scalars(select(OcrFact).where(OcrFact.expense_id == 42)).one()
        assert suggestion.parsed_merchant == "中国建设银行"
    client.post("/recognition-later-fact")
    replay = client.post(path, data=fields, headers={"Accept": "application/json"})
    assert replay.json() == first.json() and accepted == [42]
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.status) == ("后来人工核对", 12, "pending")
        assert len(db.scalars(select(OcrFact).where(OcrFact.expense_id == 42)).all()) == 1


@pytest.mark.parametrize("change", ["identity", "viewer", "version"])
def test_recognition_refuses_changed_binding_or_fact_with_original_input_retained(recognition_browser, change):
    client, scope, options, accepted = recognition_browser
    path = "/web/expenses/42/recognize-text"
    fields = _fields(client, path)
    if change == "identity":
        fields["draft_scope"] = json.dumps({**scope, "deviceId": "old-browser"})
    elif change == "viewer":
        options[0].role = "viewer"
    else:
        client.post("/recognition-later-fact")
    rejected = client.post(path, data=fields)
    assert rejected.status_code == (403 if change == "viewer" else 409), rejected.text
    retained = hidden_post_forms(rejected.text)[path]
    for name in ("idempotency_key", "expected_row_version", "draft_ref", "draft_scope", "return_filter"):
        assert retained[name] == fields[name]
    assert fields["raw_text"] in rejected.text and not accepted
    if change == "version":
        reviewed = client.post(path, data={**fields, "review_latest": "true"})
        prepared = hidden_post_forms(reviewed.text)[path]
        assert reviewed.status_code == 200 and prepared["expected_row_version"] == "12"
        assert prepared["idempotency_key"] != fields["idempotency_key"]
        assert prepared["draft_ref"] == fields["draft_ref"] and fields["raw_text"] in reviewed.text
        assert not accepted, "核对依据不能启动识别"


@pytest.mark.real_db
@pytest.mark.parametrize("kind", ["text", "image", "region"])
def test_browser_resumes_recognition_and_original_financial_draft_after_lost_reply(recognition_browser, confirmation_store, tmp_path, monkeypatch, kind):
    client, _, _, accepted = recognition_browser
    if kind == "region":
        _region_browser_input(client, confirmation_store, monkeypatch, accepted)
    result = review_tests._run_review_page(client, tmp_path,
        "/web/expenses/42/edit?ledger_id=owner&return_to=pending&recognition_probe=" + kind)
    assert not result.get("error"), result.get("error")
    assert result["restored"] and result["financial_retained"] and result["recognition_removed"]
    assert result["requests"][0] == result["requests"][1] and accepted == [42]
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.status) == ("后来人工核对", 12, "pending")


def _region_browser_input(client, store, monkeypatch, accepted):
    import io

    from PIL import Image

    from app.services.expense_service._ocr_facts import append_ocr_fact
    from app.services.file_service import resolve_upload_path_for_tenant, save_upload_bytes
    from tests.test_ocr_region_commands import _block, _retry

    buffer = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="PNG")
    saved = save_upload_bytes(buffer.getvalue(), tenant_id="owner", filename="region.png", content_type="image/png")
    with store() as db:
        resolve_write_capability(db)
        expense = db.get(Expense, 42)
        expense.image_path, expense.image_hash = saved.relative_path, saved.image_hash
        evidence = {"schema": "text-blocks/v1", "width": 120, "height": 80, "input_sha256": expense.image_hash,
            "coordinate_space": "exif-transposed-pixels", "identity": {"recipe_name": "baseline"},
            "blocks": [_block("商户：青禾超市", [0, 0, 80, 15]), _block("实付", [0, 30, 30, 45]), _block("21", [70, 30, 90, 45])]}
        append_ocr_fact(db, expense=expense, result=OcrResult(raw_text="商户：青禾超市\n实付\n21",
            confidence=0.9, evidence=evidence), provider_name="rapidocr")
        db.commit()
    monkeypatch.setattr(_ocr, "_active_provider_name", lambda: "rapidocr")
    def recognize(_path, _digest, box):
        accepted.append(42)
        return _retry(evidence, box)
    monkeypatch.setattr("app.services.ocr_region_service.recognize_region_snapshot", recognize)
    @client.app.get("/web/expenses/42/image")
    def source_image():
        return FileResponse(resolve_upload_path_for_tenant(saved.relative_path, tenant_id="owner"), media_type="image/png")


def test_async_completion_observer_keeps_open_financial_draft_and_original_occ(recognition_browser, tmp_path, monkeypatch):
    client, _, _, accepted = recognition_browser
    submitted = []
    monkeypatch.setattr("app.services.background_task_executor.submit_task",
        lambda task_id, payload, **kwargs: submitted.append((task_id, payload)))
    path = "/web/expenses/42/ocr/retry"
    response = client.post(path, data=_fields(client, path), headers={"Accept": "application/json"})
    assert response.status_code == 200 and len(submitted) == 1 and not accepted
    task_id, payload = submitted[0]

    @client.app.post("/ocr-watch-finish")
    def finish():
        run_task(task_id, payload)
        return {"done": True}

    @client.app.get("/ocr-watch-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/ocr_watch_probe.js", media_type="text/javascript")

    client.app.state.expense_review_probe = "ocr-watch-probe.js"
    result = review_tests._run_review_page(client, tmp_path, "/web/expenses/42/edit?ledger_id=owner&return_to=pending")
    assert not result.get("error"), result
    assert result["merchant"] == "识别途中未保存的商家" and result["identity_retained"]
    assert result["result_link_visible"] and result["cancel_hidden"] and not result["horizontal_overflow"]
    assert accepted == [42]


@pytest.mark.real_db
def test_recognition_keeps_unsaved_text_in_page_when_browser_cannot_retain_it(recognition_browser, tmp_path):
    client, _, _, accepted = recognition_browser
    result = review_tests._run_review_page(client, tmp_path,
        "/web/expenses/42/edit?ledger_id=owner&recognition_probe=storage")
    assert not result.get("error"), result
    assert result["leaving_prevented"] and result["retained_in_page"], result
    assert "未能保留" in result["warning"] and not accepted


@pytest.mark.parametrize("suffix", ["recognize-text", "ocr/retry"])
def test_recognition_failure_preserves_original_and_reports_through_http_owner(recognition_browser, confirmation_store, monkeypatch, caplog, suffix):
    client, _, _, _ = recognition_browser
    client.app.add_middleware(SanitizedLoggingMiddleware)
    path = "/web/expenses/42/" + suffix
    fields = _fields(client, path)
    failure = SQLAlchemyError("controlled recognition storage interruption")

    def fail(*args, **kwargs):
        raise failure

    if suffix == "ocr/retry":
        monkeypatch.setattr(ocr_tasks, "_prepare_retry", fail)
    else:
        monkeypatch.setattr(command, "prepare_pending_expense_fx", fail)
    native = client.post(path, data=fields)
    retained = hidden_post_forms(native.text)[path]
    for name in ("idempotency_key", "expected_row_version", "draft_scope", "draft_ref"):
        assert retained[name] == fields[name]
    enhanced = client.post(path, data=fields, headers={"Accept": "application/json"})
    assert enhanced.json()["draft_result"] == "blocked" and "ack" not in enhanced.json()
    for response in (native, enhanced):
        assert response.status_code == 503 and str(failure) not in response.text
        assert any(record.name == "ticketbox.http" and record.exc_info and record.exc_info[1] is failure
            and response.headers["X-Request-Id"] in record.getMessage() for record in caplog.records)
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        assert (current.row_version, current.merchant) == (4, "首次便利店")
        assert db.scalar(select(ApiIdempotencyKey)) is None

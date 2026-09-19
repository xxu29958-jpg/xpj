"""Saved CSV event forms: real routes/templates, forbidden database connections."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import Request
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
from sqlalchemy.engine import Engine
from starlette.templating import Jinja2Templates

BATCH = "eed35556-b580-468c-9406-6087538829a4"
EVENT = "a28bc45d-9fda-44b5-9f67-3b70b0819909"
ROOT = "4a21eb10-8be3-42dc-b3fe-434ce6680d88"


@pytest.fixture()
def review_web(monkeypatch):
    def no_database(*_a, **_k):
        pytest.fail("Web event probes must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from app.routes import web_import_events as route
    from app.routes.web_common import LedgerOption

    environment = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).resolve().parents[1] / "app/templates/web"),
    ]), undefined=StrictUndefined, autoescape=True)
    monkeypatch.setattr(route, "templates", Jinja2Templates(env=environment))
    options = [LedgerOption("family", "Family", "member", False, 0, 0)]
    monkeypatch.setattr(route, "_list_ledger_options", lambda _db: options)
    monkeypatch.setattr(route, "_resolve_selected_ledger_id", lambda *_a, **_k: "family")
    monkeypatch.setattr(route, "_base_ctx", lambda *_a, **_k: {
        "can_write": options[0].role != "viewer", "selected_ledger_id": "family", "csrf_token": "fixture-csrf",
    })
    monkeypatch.setattr(route, "_expense_view", lambda root: vars(root))
    return route


def row(**changes):
    from app.schemas import CsvImportRowResponse

    return CsvImportRowResponse(
        line_number=3, status="review", error_code=None, error_message=None,
        amount_cents=710, home_currency_code="CNY", original_currency_code="USD", original_amount_minor=100,
        exchange_rate_to_cny=Decimal("7.10"), exchange_rate_date=date(2026, 5, 3), exchange_rate_source="receipt",
        merchant="Coffee", category="餐饮", note="原退款", expense_time=datetime(2026, 5, 2, tzinfo=UTC),
        tags=None, source="csv", expense_id=None, entry_kind="offset", offset_kind="refund",
        source_event_public_id=EVENT, source_root_public_id=ROOT, accounting_date=date(2026, 5, 4),
        stream_amount_cents=-710, lineage_status="partially_refunded", lineage_home_net_cents=1420,
        event_input={"entry_kind": "offset"},
    ).model_copy(update=changes)


def root(**changes):
    values = {
        "id": 42, "row_version": 9, "status": "confirmed", "merchant": "Coffee", "category": "餐饮",
        "expense_time": "2026-05-02", "original_currency_code": "USD", "original_amount_value": "3.00",
        "fx_meta": "冻结汇率 7.00 · 2026-05-02", "fx_pending": False,
    }
    return SimpleNamespace(**{**values, **changes})


def request():
    req = Request({"type": "http", "path": f"/web/import/{BATCH}/rows/3/review", "headers": []})
    req.state.web_session_auth = SimpleNamespace(ledger_id="family", account_id=17, device_id=23,
        device_public_id="device-id", device_name="Web browser")
    return req


def arrange(monkeypatch, route, event, target=None):
    calls = []

    def get_row(_db, **kwargs):
        calls.append(("row", kwargs))
        return event

    def find_root(_db, expense_id, tenant_id):
        calls.append(("root", expense_id, tenant_id))
        return target

    def search(_db, **kwargs):
        calls.append(("search", kwargs))
        return ([target], 1) if target else ([], 0)

    monkeypatch.setattr(route, "get_csv_import_row", get_row)
    monkeypatch.setattr(route, "get_expense", find_root)
    monkeypatch.setattr(route, "search_import_root_expenses", search)
    return calls


def submit(route, **changes):
    values = {"request": request(), "public_id": BATCH, "line_number": 3, "ledger_id": "family",
              "expense_id": "42", "expected_row_version": "5", "reason": "核对来源收据",
              "acknowledge_incomplete_lineage": "", "manual_exchange_rate": "", "exchange_rate_date": "",
              "db": SimpleNamespace(rollback=lambda: None)}
    return route.web_import_event_submit(**{**values, **changes})


def test_review_submits_actor_scope_original_occ_and_reason(review_web, monkeypatch):
    calls = []

    def accept(_db, **kwargs):
        calls.append(kwargs)
        return row(status="applied")

    monkeypatch.setattr(review_web, "review_csv_import_row", accept)
    response = submit(review_web)
    assert response.status_code == 303
    assert calls[0]["tenant_id"] == "family"
    assert calls[0]["public_id"] == BATCH
    assert calls[0]["line_number"] == 3
    assert calls[0]["actor_account_id"] == 17 and calls[0]["actor_device_id"] == 23
    assert calls[0]["actor_device_public_id"] == "device-id"
    assert calls[0]["payload"].model_dump() == {
        "expense_id": 42, "expected_row_version": 5, "reason": "核对来源收据",
        "acknowledge_incomplete_lineage": False,
        "manual_exchange_rate": None, "exchange_rate_date": None,
    }
    target = urlsplit(response.headers["location"])
    assert target.path == f"/web/import/{BATCH}/rows/3/review"
    assert parse_qs(target.query)["ledger_id"] == ["family"]
    assert parse_qs(target.query)["msg"] == ["事件已入账。"]


def test_occ_refusal_keeps_reason_and_displays_fresh_root_before_resubmit(review_web, monkeypatch):
    from app.errors import AppError

    event = row(resolved_expense_id=42, resolved_root_status="confirmed", resolved_root_row_version=9)
    calls = arrange(monkeypatch, review_web, event, root())
    versions = []

    def refuse(_db, **kwargs):
        versions.append(kwargs["payload"].expected_row_version)
        raise AppError("state_conflict", status_code=409)

    monkeypatch.setattr(review_web, "review_csv_import_row", refuse)
    response = submit(review_web, reason="我的说明 <保留>")
    body = response.body.decode()
    assert response.status_code == 409 and versions == [5]
    assert "已载入最新原单和版本" in body
    assert "我的说明 &lt;保留&gt;" in body
    assert 'name="expected_row_version" value="9"' in body
    assert 'name="csrf_token" value="fixture-csrf"' in body
    assert 'name="ledger_id" value="family"' in body
    assert ("root", 42, "family") in calls


def test_pending_root_confirmation_link_returns_to_saved_event(review_web, monkeypatch):
    event = row(resolved_expense_id=42, resolved_root_status="pending", resolved_root_row_version=9)
    arrange(monkeypatch, review_web, event, root(status="pending"))
    response = review_web.web_import_event_review(request(), BATCH, 3, ledger_id="family", db=object())
    body = response.body.decode()
    assert "复核并确认原单，完成后返回" in body
    assert "return_to=csv_import_event" in body and f"return_import_public_id={BATCH}" in body
    assert "return_import_line_number=3" in body
    assert "return_import_expense_id=42" in body
    assert "确认原单并登记退款" not in body
    assert "来源消费时间" in body and "事件生效日期" in body
    assert "2026-05-03" in body and "receipt" in body and "7.10" in body
    assert "7.00" in body  # Source offset quote and target purchase quote stay distinct.


def test_missing_root_search_stays_in_ledger_and_explicitly_selects(review_web, monkeypatch):
    calls = arrange(monkeypatch, review_web, row(), root())
    response = review_web.web_import_event_review(request(), BATCH, 3, ledger_id="family",
        query="Coffee", page=2, reason="保留说明", db=object())
    body = response.body.decode()
    assert ("search", {"tenant_id": "family", "query": "Coffee", "page": 2, "page_size": 20}) in calls
    assert "选择此原单" in body and 'name="expense_id" value="42"' in body
    assert 'name="reason" value="保留说明"' in body
    assert "补充上传原单（新页面）" in body and "已补充原单，重新读取关联" in body
    assert "确认原单并登记退款" not in body


@pytest.mark.parametrize("field,value", [("reason", " "), ("expense_id", "bad"), ("expected_row_version", "0")])
def test_invalid_review_input_is_retained_without_command(review_web, monkeypatch, field, value):
    arrange(monkeypatch, review_web, row(), root())
    monkeypatch.setattr(review_web, "review_csv_import_row", lambda *_a, **_k: pytest.fail("invalid command"))
    response = submit(review_web, **{field: value})
    assert response.status_code == 422
    assert 'role="alert"' in response.body.decode()


def test_viewer_cannot_submit_and_has_no_mutation_form(review_web, monkeypatch):
    from app.errors import AppError
    from app.routes.web_common import LedgerOption

    monkeypatch.setattr(review_web, "_list_ledger_options", lambda _: [LedgerOption("family", "Family", "viewer", False, 0, 0)])
    monkeypatch.setattr(review_web, "_base_ctx", lambda *_a, **_k: {
        "can_write": False, "selected_ledger_id": "family", "csrf_token": "fixture-csrf",
    })
    monkeypatch.setattr(review_web, "review_csv_import_row", lambda *_a, **_k: pytest.fail("viewer write"))
    arrange(monkeypatch, review_web, row(resolved_expense_id=42), root())
    response = review_web.web_import_event_review(request(), BATCH, 3, ledger_id="family", db=object())
    assert 'method="post"' not in response.body.decode()
    with pytest.raises(AppError) as caught:
        submit(review_web)
    assert caught.value.status_code == 403


def test_ledger_switch_preserves_original_form_without_review(review_web, monkeypatch):
    from fastapi.responses import HTMLResponse

    captured = []

    def retain(_request, _db, **kwargs):
        captured.append(kwargs)
        return HTMLResponse("retained", status_code=409)

    monkeypatch.setattr(review_web, "preserve_original_ledger_form", retain)
    monkeypatch.setattr(review_web, "review_csv_import_row", lambda *_a, **_k: pytest.fail("retargeted write"))
    response = submit(review_web, ledger_id="old-family", reason="原始草稿")
    assert response.status_code == 409
    assert captured[0]["fields"]["ledger_id"] == "old-family"
    assert captured[0]["fields"]["reason"] == "原始草稿"
    assert captured[0]["selected"] == "family"


def test_incomplete_purchase_explicit_ack_and_historical_null_quote_display(review_web, monkeypatch):
    event = row(entry_kind="expense", offset_kind=None, exchange_rate_to_cny=None,
                exchange_rate_date=None, exchange_rate_source=None)
    arrange(monkeypatch, review_web, event)
    response = review_web.web_import_event_review(request(), BATCH, 3, ledger_id="family", db=object())
    body = response.body.decode()
    assert 'name="acknowledge_incomplete_lineage" value="true"' in body
    assert "未导入的退款、拒付或冲销不会自动生成" in body
    assert "文件未提供汇率" in body and "未携带冻结汇率证据的历史行" in body
    assert "1 USD = 7.10 CNY" not in body
    assert 'name="manual_exchange_rate"' in body and 'name="exchange_rate_date"' in body
    payloads = []

    def accept(_db, **kwargs):
        payloads.append(kwargs["payload"])
        return event.model_copy(update={"status": "applied"})

    monkeypatch.setattr(review_web, "review_csv_import_row", accept)
    submit(review_web, expense_id="", expected_row_version="", acknowledge_incomplete_lineage="true")
    assert payloads[0].acknowledge_incomplete_lineage is True
    assert payloads[0].expense_id is None


@pytest.mark.parametrize("status", ["applied", "matched", "conflict"])
def test_completed_or_conflicting_event_keeps_result_and_correction_paths(review_web, monkeypatch, status):
    arrange(monkeypatch, review_web, row(status=status, resolved_expense_id=42,
        resolved_offset_public_id=EVENT), root())
    response = review_web.web_import_event_review(request(), BATCH, 3, ledger_id="family", db=object())
    body = response.body.decode()
    assert 'method="post"' not in body
    assert "查看原单与退款记录" in body
    assert "返回原批次" in body and EVENT in body
    assert ("下载错误行 CSV" in body) == (status == "conflict")


def test_batch_lists_existing_drafts_reviews_and_confirmed_offsets_separately(review_web):
    from app.services.csv_import_batch_service._queries import CsvImportBatchProgress, CsvImportRowCounts

    batch = SimpleNamespace(public_id=BATCH, file_name="events.csv", total_rows=4, last_error=None)
    counts = CsvImportRowCounts(remaining_valid_rows=0, applied_rows=2, matched_rows=1,
                               review_rows=1, confirmed_offset_rows=1)
    rows = [row(status="matched"), row(status="applied", entry_kind="expense", offset_kind=None),
            row(status="review", offset_kind="chargeback"), row(status="applied", offset_kind="reversal")]
    context = {
        "batch": batch, "progress": CsvImportBatchProgress(batch, counts), "created_label": "May 2026",
        "updated_label": "May 2026", "q": "?ledger_id=family", "selected_ledger_id": "family",
        "can_write": True, "csrf_token": "fixture-csrf", "flash_message": "", "flash_type": "success",
        "rows": rows, "current_expenses": {}, "row_amount_label": review_web._minor_amount_label,
        "page": 1, "page_size": 100, "total": 4, "total_pages": 1, "status": "",
    }
    body = review_web.templates.env.get_template("import_batch.html").render(context)
    for expected in ("已有记录", "新消费草稿", "待复核", "事件已入账", "支出", "退款", "拒付", "冲销"):
        assert expected in body
    assert "本批次新增 1 条消费草稿" in body
    assert f'/web/import/{BATCH}/rows/3/review?ledger_id=family' in body
    assert 'name="status"' in body and 'value="matched"' in body and 'value="review"' in body


def test_manual_quote_failure_preserves_inputs_and_frozen_quote_is_read_only(review_web, monkeypatch):
    from app.errors import AppError

    event = row(resolved_expense_id=42, exchange_rate_to_cny=None, exchange_rate_date=None,
                exchange_rate_source=None)
    arrange(monkeypatch, review_web, event, root())

    def refuse(_db, **_kwargs):
        raise AppError("invalid_request", "补录汇率与文件金额不一致。", status_code=422)

    monkeypatch.setattr(review_web, "review_csv_import_row", refuse)
    response = submit(review_web, manual_exchange_rate="7.2", exchange_rate_date="2026-05-03")
    body = response.body.decode()
    assert response.status_code == 422
    assert 'name="manual_exchange_rate" inputmode="decimal" value="7.2"' in body
    assert 'name="exchange_rate_date" value="2026-05-03"' in body
    assert "核对来源收据" in body
    arrange(monkeypatch, review_web, row(resolved_expense_id=42), root())
    response = review_web.web_import_event_review(request(), BATCH, 3, ledger_id="family", db=object())
    assert 'name="manual_exchange_rate"' not in response.body.decode()


def test_upload_cannot_silently_move_to_the_new_live_ledger(review_web, monkeypatch):
    from app.routes import web_import_export

    monkeypatch.setattr(web_import_export, "_list_ledger_options", review_web._list_ledger_options)
    monkeypatch.setattr(web_import_export, "_resolve_selected_ledger_id", review_web._resolve_selected_ledger_id)
    monkeypatch.setattr(web_import_export, "create_csv_import_batch", lambda *_a, **_k: pytest.fail("wrong-ledger upload"))
    response = asyncio.run(web_import_export.web_import_preview(request(), ledger_id="old-family",
                                                                csv_file=object(), db=object()))
    target = parse_qs(urlsplit(response.headers["location"]).query)
    assert response.status_code == 303
    assert target["flash_type"] == ["error"]
    assert target["ledger_id"] == ["family"]
    assert "本次文件尚未导入" in target["msg"][0]

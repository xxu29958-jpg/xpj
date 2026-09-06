"""CSV recovery route and real detail actions; database connections are forbidden."""

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from _web_native_form_support import hidden_post_forms
from fastapi import Request
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
from sqlalchemy.engine import Engine


@pytest.fixture()
def import_route(monkeypatch):
    def no_database(*_args, **_kwargs):
        pytest.fail("CSV route/action probe must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from app.routes import web_import_export
    from app.routes.web_common import LedgerOption

    options = [LedgerOption("family", "Family", "member", False, 0, 0)]
    monkeypatch.setattr(web_import_export, "_list_ledger_options", lambda _db: options)
    monkeypatch.setattr(web_import_export, "_resolve_selected_ledger_id", lambda *_a, **_k: "family")
    return web_import_export


@pytest.mark.parametrize("missing", [False, True], ids=["active-lease", "missing-batch"])
def test_apply_refusal_retains_only_a_recoverable_original_batch(import_route, monkeypatch, missing):
    from app.errors import AppError

    calls = []

    def refuse_apply(_db, **kwargs):
        calls.append(kwargs)
        if missing:
            raise AppError("import_batch_not_found", "导入批次不存在。", status_code=404)
        raise AppError("invalid_request", "导入批次正在应用中，请稍后重试。", status_code=409)

    monkeypatch.setattr(import_route, "apply_csv_import_batch", refuse_apply)
    request = Request({"type": "http", "path": "/web/import/original/apply", "headers": []})
    response = import_route.web_import_batch_apply(
        request, public_id="original", ledger_id="family", batch_size=1, db=object(),
    )

    assert calls == [{
        "tenant_id": "family", "public_id": "original", "batch_size": 1, "desktop_session": None,
    }]
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert parse_qs(target.query).get("flash_type") == ["error"]
    assert target.path == ("/web/import" if missing else "/web/import/original")
    assert parse_qs(target.query)["ledger_id"] == ["family"]
    assert parse_qs(target.query)["msg"] == ["导入批次不存在。" if missing else "导入批次正在应用中，请稍后重试。"]


@pytest.mark.parametrize(
    "status,total,valid,applied,errors",
    [("parsed_with_errors", 1, 0, 0, 1), ("applied_with_errors", 2, 2, 1, 1), ("applied", 1, 1, 1, 0)],
    ids=["all-invalid", "insert-failed-after-partial-success", "completed"],
)
def test_batch_actions_follow_effective_remainder_and_actual_applied_rows(
    import_route, status, total, valid, applied, errors,
):
    from app.services.csv_import_batch_service._queries import CsvImportBatchPage, CsvImportBatchProgress

    environment = Environment(
        loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(Path(__file__).resolve().parents[1] / "app/templates/web"),
        ]),
        undefined=StrictUndefined,
        autoescape=True,
    )
    batch = SimpleNamespace(
        public_id="original", file_name="saved.csv", status=status, total_rows=total,
        valid_rows=valid, applied_rows=applied, error_rows=errors, last_error=None,
    )
    flash_type = "success" if status == "applied" else "error"
    context = {
        "batch": batch, "progress": CsvImportBatchProgress(batch, remaining_valid_rows=0),
        "created_label": "2026-06-01", "updated_label": "2026-06-01",
        "q": "?ledger_id=family", "selected_ledger_id": "family", "can_write": True, "csrf_token": "fixture",
        "flash_message": "Import result", "flash_type": flash_type,
        "rows": [], "page": 1, "page_size": 100, "total": 0, "total_pages": 1,
        "status": "", "home_currency_symbol": "¥", "base_batch_url": "/web/import/original?ledger_id=family",
        "batch_page": CsvImportBatchPage([], page=1, page_size=20, total=0, total_pages=1),
        "batch_created_labels": {}, "max_rows": 1000, "export_categories": [], "export_tags": [],
    }
    body = environment.get_template("import_batch.html").render(context)
    hub = environment.get_template("import_export.html").render(context)

    role = "status" if flash_type == "success" else "alert"
    for rendered in (hub, body):
        assert f'role="{role}"' in rendered
        assert ("product-feedback--error" in rendered) == (flash_type == "error")
    assert "/web/import/original/apply" not in hidden_post_forms(body)
    assert ('href="/web/pending?ledger_id=family"' in body) == (applied > 0)
    assert ('href="/web/import/original/errors.csv?ledger_id=family"' in body) == (errors > 0)
    if applied < valid or applied == 0:
        assert "本批次的可导入行已全部进入" not in body

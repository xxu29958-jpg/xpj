"""Rejected native recurring forms preserve intentions independently of facts."""

import re
from html import unescape
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import RecurringItem
from app.routes import web_recurring as recurring_routes
from app.routes.web_app import _require_local as _web_require_local
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc
from tests._web_native_form_support import hidden_post_forms
from tests._web_recurring_test_support import row_version, seed_observed_item


@pytest.fixture()
def web_recurring(client):
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _form(page, action):
    matched = re.search(r'<form[^>]*action="' + re.escape(action) + r'".*?</form>', page.text, re.DOTALL)
    assert matched is not None, page.text
    form = matched.group(0)
    fields = hidden_post_forms(form)[action]
    selector = re.search(r'<select\b[^>]*name="home_currency_code"[^>]*>(.*?)</select>', form, re.DOTALL)
    if selector:
        selected = re.search(r'<option\b[^>]*value="([^"]*)"[^>]*selected', selector.group(1))
        assert selected is not None, "The native form must select its captured original currency"
        fields["home_currency_code"] = unescape(selected.group(1))
    return form, fields


def test_create_validation_preserves_fields_and_original_key_until_single_success(web_recurring):
    client = web_recurring
    action = "/web/recurring/create"
    _, fields = _form(client.get("/web/recurring?ledger_id=owner"), action)
    fields.update(merchant="房租与物业", baseline_amount_yuan="0", next_expected_date="")
    refused = client.post(action, data=fields)
    form, retained = _form(refused, action)
    assert 'value="房租与物业"' in form and 'value="0"' in form
    assert retained["idempotency_key"] == fields["idempotency_key"]
    assert 'name="next_expected_date" value=""' in form
    fields["baseline_amount_yuan"] = "3800.25"
    assert client.post(action, data=fields, follow_redirects=False).status_code == 303
    assert client.post(action, data=fields, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        items = list(db.scalars(select(RecurringItem).where(RecurringItem.merchant_name == "房租与物业")))
        assert len(items) == 1 and items[0].baseline_amount_cents == 380025
        assert items[0].next_expected_date is None


def test_edit_conflict_preserves_proposal_and_review_does_not_write(web_recurring):
    client = web_recurring
    public_id = seed_observed_item(merchant="房租", source="manual", occurrence_count=0)
    action = f"/web/recurring/{public_id}/edit"
    _, fields = _form(client.get("/web/recurring?ledger_id=owner"), action)
    fields.update(merchant="房租与物业", baseline_amount_yuan="3500.25", next_expected_date="")
    parallel = {**fields, "merchant": "另一端的房租", "baseline_amount_yuan": "3200", "idempotency_key": str(uuid4())}
    assert client.post(action, data=parallel, follow_redirects=False).status_code == 303
    version = row_version(public_id)
    refused = client.post(action, data=fields)
    form, retained = _form(refused, action)
    assert 'value="房租与物业"' in form and 'value="3500.25"' in form
    assert all(retained[key] == fields[key] for key in ("idempotency_key", "expected_row_version"))
    assert 'name="review_latest"' in form
    reviewed = client.post(action, data={**fields, "review_latest": "true"})
    form, proposal = _form(reviewed, action)
    assert 'value="房租与物业"' in form and 'value="3500.25"' in form
    assert proposal["idempotency_key"] != fields["idempotency_key"]
    assert int(proposal["expected_row_version"]) == version == row_version(public_id)
    proposal.update(merchant="房租与物业", baseline_amount_yuan="3500.25", next_expected_date="")
    assert client.post(action, data=proposal, follow_redirects=False).status_code == 303
    assert client.post(action, data=proposal, follow_redirects=False).status_code == 303
    assert row_version(public_id) == version + 1
    proposal["baseline_amount_yuan"] = "3600.25"
    form, retained = _form(client.post(action, data=proposal), action)
    assert 'value="3600.25"' in form and 'name="review_latest"' in form
    assert retained["idempotency_key"] == proposal["idempotency_key"]
    assert row_version(public_id) == version + 1


def test_pending_create_retains_original_intent_without_a_new_key_exit(web_recurring, monkeypatch):
    client = web_recurring
    action = "/web/recurring/create"
    _, fields = _form(client.get("/web/recurring?ledger_id=owner"), action)
    fields.update(merchant="处理中房租", baseline_amount_yuan="3500", next_expected_date="")

    def pending(*args, **kwargs):
        raise AppError("idempotency_key_in_progress", status_code=409)

    monkeypatch.setattr(recurring_routes, "create_manual_recurring_item", pending)
    form, retained = _form(client.post(action, data=fields), action)
    assert 'value="处理中房租"' in form and 'value="3500"' in form
    assert retained["idempotency_key"] == fields["idempotency_key"]
    assert 'name="review_latest"' not in form


def test_archived_edit_keeps_input_readable_without_a_write_exit(web_recurring):
    client = web_recurring
    public_id = seed_observed_item(merchant="房租", source="manual", occurrence_count=0)
    action = f"/web/recurring/{public_id}/edit"
    _, fields = _form(client.get("/web/recurring?ledger_id=owner"), action)
    fields.update(merchant="保留的房租调整", baseline_amount_yuan="3500", next_expected_date="")
    assert client.post(f"/web/recurring/{public_id}/archive", data={"ledger_id": "owner"}, follow_redirects=False).status_code == 303
    version = row_version(public_id)
    form, retained = _form(client.post(action, data=fields), action)
    assert 'value="保留的房租调整"' in form and 'value="3500"' in form
    assert retained["idempotency_key"] == fields["idempotency_key"]
    assert 'type="submit"' not in form
    assert row_version(public_id) == version


def test_recurring_form_keeps_jpy_record_and_raw_input_under_cny_default(web_recurring):
    with SessionLocal() as db:
        resolve_write_capability(db)
        item = RecurringItem(tenant_id="owner", merchant_key="jpy-subscription", merchant_name="日元订阅",
            home_currency_code="JPY", baseline_amount_cents=1200, last_amount_cents=1200,
            occurrence_count=0, source="manual", status="active", frequency="monthly",
            created_at=now_utc(), updated_at=now_utc())
        db.add(item)
        db.commit()
        public_id = item.public_id
    action = f"/web/recurring/{public_id}/edit"
    form, fields = _form(web_recurring.get("/web/recurring?ledger_id=owner"), action)
    assert fields["home_currency_code"] == "JPY"
    assert 'value="1200"' in form and 'step="1"' in form
    fields.update(merchant="日元订阅", baseline_amount_yuan="1300", next_expected_date="")
    assert web_recurring.post(action, data=fields, follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        saved = db.scalar(select(RecurringItem).where(RecurringItem.public_id == public_id))
        assert (saved.home_currency_code, saved.baseline_amount_cents, saved.row_version) == ("JPY", 1300, 2)
    incompatible = {**fields, "home_currency_code": "CNY", "baseline_amount_yuan": "14.50",
        "expected_row_version": "2", "idempotency_key": str(uuid4())}
    refused = web_recurring.post(action, data=incompatible)
    form, retained = _form(refused, action)
    assert retained["home_currency_code"] == "CNY" and retained["idempotency_key"] == incompatible["idempotency_key"]
    assert 'value="14.50"' in form and "编辑当前记录" in refused.text
    assert 'name="review_latest"' not in form
    assert row_version(public_id) == 2


def test_create_without_captured_currency_preserves_raw_text_and_does_not_infer_cny(web_recurring):
    action = "/web/recurring/create"
    _, fields = _form(web_recurring.get("/web/recurring?ledger_id=owner"), action)
    fields.pop("home_currency_code")
    fields.update(merchant="缺币种原填写", baseline_amount_yuan="1200.50", next_expected_date="")
    form, retained = _form(web_recurring.post(action, data=fields), action)
    assert retained["home_currency_code"] == ""
    assert retained["idempotency_key"] == fields["idempotency_key"]
    assert 'value="1200.50"' in form and 'name="review_latest"' not in form
    with SessionLocal() as db:
        assert db.scalar(select(RecurringItem).where(RecurringItem.merchant_name == fields["merchant"])) is None

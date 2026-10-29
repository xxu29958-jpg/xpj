"""Web sessions consume the same retained bill and financial command as Android."""
import html
import json
import re
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Debt, DebtBillCapture, Expense
from app.routes import web_debt_bills, web_debt_create
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services import debt_bill_source_parse
from app.services.debt_bill_parse_service import MockDebtBillProvider
from tests._infra.assets import PNG_BYTES
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client
from tests.family_ledger_test_support import set_owner_ledger_role

pytestmark = pytest.mark.real_db


def input_value(page, name):
    match = re.search(rf'name="{name}"[^>]*value="([^"]*)"', page)
    assert match is not None, name
    return html.unescape(match.group(1))


@pytest.fixture()
def browser_task(client, identity):
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity), domain=PUBLIC_HOST, path="/")
    page = browser.get("/web/debts/new?ledger_id=owner")
    assert page.status_code == 200, page.text
    scope = re.search(r'data-debtcreation-draft-scope="([^"]+)"', page.text)
    assert scope is not None
    binding = {"ledger_id": "owner", "draft_scope": html.unescape(scope.group(1)),
        "csrf_token": input_value(page.text, "csrf_token")}
    form = {**binding, "idempotency_key": str(uuid4()), "home_currency_code": "CNY", "currency_code": "CNY",
        "direction": "i_owe", "counterparty_label": "Bill test", "amount_major": "120.00", "note": "",
        "event_time": input_value(page.text, "event_time"), "calendar_revision": input_value(page.text, "calendar_revision"),
        "debt_kind": "unspecified", "installment_count": "", "installment_period_months": ""}
    headers = {"Origin": f"https://{PUBLIC_HOST}", "Accept": "application/json", "X-CSRF-Token": binding["csrf_token"]}
    yield browser, binding, form, headers
    browser.close()


def upload(browser_task, *, key=None, override=None):
    browser, binding, form, headers = browser_task
    data = {**binding, "creation_key": form["idempotency_key"], "idempotency_key": key or str(uuid4()), **(override or {})}
    return browser.post("/web/debt-bills", data=data, headers=headers,
        files={"file": ("bill.png", PNG_BYTES, "image/png")})


def command(browser_task, source, action, *, key=None):
    browser, binding, _, headers = browser_task
    paths = {"parse": f"/web/debt-bills/{source['public_id']}/parse",
        "discard": f"/web/debt-bills/{source['public_id']}/discard"}
    return browser.post(paths[action], headers=headers,
        json={key: value for key, value in {**binding, "expected_row_version": source["row_version"],
            "idempotency_key": key or str(uuid4())}.items() if key != "csrf_token"})


def test_web_capture_parse_create_and_android_read_share_one_source_and_fact(browser_task, client, identity, monkeypatch):
    monkeypatch.setattr(debt_bill_source_parse, "get_debt_bill_provider", MockDebtBillProvider)
    browser, _, form, headers = browser_task
    capture_key = str(uuid4())
    accepted = upload(browser_task, key=capture_key)
    assert accepted.status_code == 200, accepted.text
    source = accepted.json()
    assert upload(browser_task, key=capture_key).json() == source
    assert browser.get(f"/web/debt-bills/by-key/{capture_key}?ledger_id=owner").json()["public_id"] == source["public_id"]
    parse_key = str(uuid4())
    parsed = command(browser_task, source, "parse", key=parse_key)
    assert parsed.status_code == 200, parsed.text
    assert parsed.json()["status"] == "succeeded"
    assert command(browser_task, source, "parse", key=parse_key).json() == parsed.json()
    assert browser.get(f"/web/debt-bills/{source['public_id']}/parse-attempts/{parse_key}?ledger_id=owner").json() == parsed.json()
    form.update(bill_source_public_id=source["public_id"], bill_source_row_version=str(parsed.json()["row_version"]))
    created = browser.post("/web/debts", data=form, headers=headers)
    assert created.status_code == 200, created.text
    debt = created.json()["receipt"]
    assert browser.post("/web/debts", data=form, headers=headers).json() == created.json()
    source_read = browser.get(f"/web/debt-bills/{source['public_id']}?ledger_id=owner").json()
    assert source_read["status"] == "confirmed" and source_read["adopted_debt_public_id"] == debt["public_id"]
    assert client.get(f"/api/debt-bills/{source['public_id']}", headers=identity.app_headers).json() == source_read
    assert client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()["principal_amount_cents"] == 12000
    original = browser.get(f"/web/debt-bills/{source['public_id']}/original?ledger_id=owner")
    assert original.status_code == 200 and original.content == PNG_BYTES
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 1
        assert db.scalar(select(func.count()).select_from(DebtBillCapture)) == 1
        assert db.scalar(select(func.count()).select_from(Expense)) == 0


@pytest.mark.parametrize("refusal", ["viewer", "wrong_ledger", "wrong_binding", "missing_csrf"])
def test_capture_refusal_preserves_original_request_without_creating_source(browser_task, refusal):
    browser, binding, _, headers = browser_task
    override = {}
    if refusal == "viewer":
        set_owner_ledger_role("viewer")
    elif refusal == "wrong_ledger":
        override["ledger_id"] = "tester_1"
    elif refusal == "wrong_binding":
        scope = json.loads(binding["draft_scope"])
        scope["ledgerId"] = "tester_1"
        override["draft_scope"] = json.dumps(scope)
    else:
        headers.pop("X-CSRF-Token")
        override["csrf_token"] = ""
    response = upload(browser_task, override=override)
    assert response.status_code in {403, 409}, response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DebtBillCapture)) == 0
        assert db.scalar(select(func.count()).select_from(Debt)) == 0


def test_discard_replays_and_prevents_adoption_but_preserves_original(browser_task):
    browser, _, form, headers = browser_task
    accepted = upload(browser_task)
    assert accepted.status_code == 200, accepted.text
    source = accepted.json()
    key = str(uuid4())
    discarded = command(browser_task, source, "discard", key=key)
    assert discarded.status_code == 200, discarded.text
    assert command(browser_task, source, "discard", key=key).json() == discarded.json()
    form.update(bill_source_public_id=source["public_id"], bill_source_row_version=str(discarded.json()["row_version"]))
    assert browser.post("/web/debts", data=form, headers=headers).status_code == 409
    original = browser.get(f"/web/debt-bills/{source['public_id']}/original?ledger_id=owner")
    assert original.status_code == 200 and original.content == PNG_BYTES


def test_lost_upload_and_financial_ack_recover_from_pg_in_a_reopened_browser(browser_task, monkeypatch):
    browser, binding, form, headers = browser_task
    capture_key = str(uuid4())
    capture_owner = web_debt_bills.capture_bill

    def lose_upload_ack(*args, **kwargs):
        capture_owner(*args, **kwargs)
        raise ConnectionResetError("synthetic lost upload acknowledgement")

    monkeypatch.setattr(web_debt_bills, "capture_bill", lose_upload_ack)
    with pytest.raises(ConnectionResetError):
        upload(browser_task, key=capture_key)
    monkeypatch.setattr(web_debt_bills, "capture_bill", capture_owner)
    recovered = browser.get(f"/web/debt-bills/by-key/{capture_key}?ledger_id=owner")
    assert recovered.status_code == 200, recovered.text
    source = recovered.json()
    assert source["status"] == "pending"
    assert upload(browser_task, key=capture_key).json()["public_id"] == source["public_id"]
    form.update(bill_source_public_id=source["public_id"], bill_source_row_version=str(source["row_version"]))
    receipt_writer = web_debt_create._creation_receipt_response

    def lose_financial_ack(*args, **kwargs):
        raise ConnectionResetError("synthetic lost financial acknowledgement")

    monkeypatch.setattr(web_debt_create, "_creation_receipt_response", lose_financial_ack)
    with pytest.raises(ConnectionResetError):
        browser.post("/web/debts", data=form, headers=headers)
    monkeypatch.setattr(web_debt_create, "_creation_receipt_response", receipt_writer)
    # A new HTTP consumer has no in-process capture/command state. Keep the
    # original cookie, draft binding, key, body and OCC; never mint a new intent.
    reopened = public_client()
    reopened.cookies.update(browser.cookies)
    try:
        response = reopened.post("/web/debts", data=form, headers=headers)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["ack"]["clientRef"] == form["idempotency_key"]
        assert receipt["ack"]["scope"] == json.loads(binding["draft_scope"])
        listed = reopened.get("/web/debt-bills", params={"ledger_id": "owner", "creation_key": form["idempotency_key"]}).json()
        assert len(listed["captures"]) == 1
        assert listed["captures"][0]["adopted_debt_public_id"] == receipt["receipt"]["public_id"]
        assert reopened.get(f"/web/debt-bills/{source['public_id']}/original?ledger_id=owner").content == PNG_BYTES
    finally:
        reopened.close()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 1
        assert db.scalar(select(func.count()).select_from(DebtBillCapture)) == 1


@pytest.mark.parametrize("refusal", ["revoked", "different_creation", "stale_source"])
def test_adoption_keeps_pending_source_on_refusal(browser_task, refusal):
    browser, _, form, headers = browser_task
    source = upload(browser_task).json()
    form.update(bill_source_public_id=source["public_id"], bill_source_row_version=str(source["row_version"]))
    if refusal == "revoked":
        set_owner_ledger_role("viewer")
        status = 403
    elif refusal == "different_creation":
        form["idempotency_key"] = str(uuid4())
        status = 422
    else:
        form["bill_source_row_version"] = str(source["row_version"] + 1)
        status = 409
    response = browser.post("/web/debts", data=form, headers=headers)
    assert response.status_code == status, response.text
    read = browser.get(f"/web/debt-bills/{source['public_id']}?ledger_id=owner")
    assert read.status_code == 200 and read.json()["status"] == "pending"
    assert browser.get(f"/web/debt-bills/{source['public_id']}?ledger_id=tester_1").status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 0

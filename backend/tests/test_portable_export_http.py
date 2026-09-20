"""Real PostgreSQL and browser-session qualification for the portable outlet."""

import json
from io import BytesIO
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Ledger, LedgerMember
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client
from tests.test_original_attachment_api import _bill, _financial_snapshot

pytestmark = pytest.mark.real_db


def _assert_bill_and_unverified_original(response, expense_id, original_bytes):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    with ZipFile(BytesIO(response.content)) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["ledger_id"] == "owner" and manifest["records_complete"] is True
        assert manifest["restore_image"] is False and manifest["includes_client_unsubmitted_intents"] is False
        expenses = [json.loads(line) for line in package.read("records/expenses.jsonl").splitlines()]
        assert any(row["id"] == expense_id and row["amount_cents"] == 1234 for row in expenses)
        originals = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
        original = next(row for row in originals if row["reference_id"] == f"expense:{expense_id}:current")
        assert original["state"] == "unverified"
        assert package.read(original["path"]) == original_bytes


def test_api_and_real_browser_viewer_download_without_filters_or_cross_ledger_disclosure(client, identity) -> None:
    expense_id, _, source = _bill(client, identity, legacy=True)
    before = _financial_snapshot(expense_id)
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity), domain=PUBLIC_HOST, path="/")
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner",
                                                    LedgerMember.account_id == ledger.owner_account_id))
        member.role = "viewer"
        db.commit()
    assert client.get("/api/exports/portable").status_code == 401
    api = client.get("/api/exports/portable", headers=identity.app_headers, params={"month": "1999-01"})
    _assert_bill_and_unverified_original(api, expense_id, source.read_bytes())
    page = browser.get("/web/import?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert 'href="/web/export/portable?ledger_id=owner"' in page.text
    assert 'action="/web/export.csv"' in page.text
    web = browser.get("/web/export/portable?ledger_id=owner&month=1999-01")
    _assert_bill_and_unverified_original(web, expense_id, source.read_bytes())
    assert browser.get("/web/export/portable?ledger_id=tester_1").status_code == 403
    other = client.get("/api/exports/portable", headers=identity.gray_app_headers)
    assert other.status_code == 200, other.text
    with ZipFile(BytesIO(other.content)) as package:
        assert json.loads(package.read("manifest.json"))["ledger_id"] == "tester_1"
        assert package.read("records/expenses.jsonl") == b""
    assert _financial_snapshot(expense_id) == before

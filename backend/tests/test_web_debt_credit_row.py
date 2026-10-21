"""A credit account's row in 往来 names the account instead of a misleading principal.

A credit account's debt moves with the account's purchases, repayments and
refunds; its stored principal is only the opening balance. The row used to read
"我欠花呗 · CNY · 本金 ¥0.00" next to ¥37.90 owed. Ordinary debts keep their principal.
"""

from __future__ import annotations

import re
from html import unescape

import pytest

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.schemas import DebtCreateRequest
from app.services.debt_service import create_debt
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms


@pytest.fixture()
def installed_debt_web():
    yield from installed_web_setup()


def _row_text(page: str, name: str) -> tuple[str, str]:
    row = re.search(r'<a class="product-entry[^"]*"[^>]*aria-label="([^"]*)"[^>]*>(?:(?!</a>).)*?<strong>' + re.escape(name)
        + r'</strong>(?:(?!</a>).)*?</a>', page, re.S)
    assert row, page[:2000]
    meta = re.search(r"<span>([^<]*)", row.group(0).split(f"<strong>{name}</strong>", 1)[1].split("</span>", 1)[1])
    return unescape(row.group(1)), unescape(meta.group(1)).strip()


@pytest.mark.currency_binding_unbound
def test_credit_account_row_names_the_account_and_ordinary_debts_keep_their_principal(installed_debt_web) -> None:
    installed = installed_debt_web
    token = _connect_local_session(installed, next_url="/web/funds")
    cookie = f"{SESSION_COOKIE_NAME}={token}"
    page = installed.browser.get("/web/funds?task=create", headers={"Cookie": cookie})
    headers = {"Cookie": f"{cookie}; {CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}",
        "Origin": "http://127.0.0.1:8000", "Accept": "application/json"}
    fields = hidden_post_forms(page.text)["/web/funds/save"]
    fields.update(name="花呗", kind="credit", currency_code="CNY", opening_amount="37.90", visibility="ledger",
        opening_source="本人对账", occurred_on="2026-10-18", institution="", tail="")
    saved = installed.browser.post("/web/funds/save", data=fields, headers=headers)
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        create_debt(db, tenant_id=saved.json()["receipt"]["ledger_id"], created_by_account_id=installed.installation_account_id,
            owner_account_id=installed.installation_account_id, payload=DebtCreateRequest(home_currency_code="CNY",
                direction="i_owe", counterparty_type="external", counterparty_label="家人甲", principal_amount_cents=120000))

    debts = installed.browser.get("/web/debts", headers=headers)
    assert debts.status_code == 200, debts.text[:500]
    credit_label, credit_meta = _row_text(debts.text, "花呗")
    assert credit_meta.endswith("· CNY · 信用账户") and "本金" not in credit_meta
    assert credit_label.endswith("信用账户") and "本金" not in credit_label
    assert "剩余 CNY ¥37.90" in credit_label
    family_label, family_meta = _row_text(debts.text, "家人甲")
    assert family_meta.endswith("· CNY · 本金 ¥1,200.00") and family_label.endswith("本金 ¥1,200.00")

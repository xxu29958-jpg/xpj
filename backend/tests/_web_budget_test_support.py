"""Shared local Web client and one actual budget-save setup."""

import json
from uuid import uuid4

from _web_recurring_test_support import open_recurring_form
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.services.identity_service import authenticate_web_session_token
from app.services.manual_expense_draft_presenter import manual_draft_scope
from tests._local_web_identity_support import _connect_local_session
from tests._web_native_form_support import hidden_post_forms


def _save_budget(web_client: TestClient, *, total: str = "1000.00") -> None:
    response = web_client.post(
        "/web/budgets/save",
        data={"home_currency_code": "CNY", "expected_row_version": "null", "idempotency_key": str(uuid4()),
            "ledger_id": "owner",
            "month": "2026-05",
            "total_amount_yuan": total,
            "rollover_amount_yuan": "50.00",
            "non_monthly_amount_yuan": "120.00",
            "excluded_category": ["医疗"],
            "excluded_categories": "报销",
            "category_budget_category": ["餐饮", "交通"],
            "category_budget_amount_yuan": ["100.00", "50.00"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


MONTH = "2026-09"


def _scope(token):
    with SessionLocal() as db:
        return manual_draft_scope(db, authenticate_web_session_token(db, token, ttl_seconds=8 * 60 * 60).auth)


def _form(browser, kind, *, public_id="", amount="15.00"):
    path = {"budget": "/web/budgets", "arrangement": "/web/budget-advise"}.get(kind, "/web/recurring")
    page = browser.get(path, params={"month": MONTH})
    assert page.status_code == 200, page.text
    if kind.startswith("recurring"):
        page = open_recurring_form(browser, page, public_id=public_id)
    action = {"budget": "/web/budgets/save", "arrangement": "/web/budget-advise/save",
        "recurring-create": "/web/recurring/create", "recurring-edit": f"/web/recurring/{public_id}/edit"}[kind]
    form_action = path if kind == "arrangement" else action
    fields = hidden_post_forms(page.text)[form_action]
    if kind == "budget":
        fields.update(total_amount_yuan=amount, rollover_amount_yuan="-1.00", non_monthly_amount_yuan="0.00",
            excluded_categories="", category_budget_category=["餐饮", "交通"], category_budget_amount_yuan=["5.00", "2.00"],
            category_budget_remove=["1"], return_category="餐饮", return_month=MONTH)
    elif kind == "arrangement":
        fields.update(savings_target_yuan=amount, reserved_buffer_yuan="2.00")
    else:
        fields.update(merchant="原固定支出", baseline_amount_yuan=amount, home_currency_code="CNY", next_expected_date="2026-10-09")
    return action, fields


def _original(installed, kind):
    scope = _scope(_connect_local_session(installed))
    browser = installed.browser
    browser.base_url = browser.base_url.copy_with(scheme="https")
    headers = {"Origin": str(browser.base_url).rstrip("/"), "Accept": "application/json"}
    public_id = ""
    if kind == "recurring-edit":
        action, seed = _form(browser, "recurring-create", amount="10.00")
        created = browser.post(action, data=seed, headers=headers)
        assert created.status_code == 200, created.text
        public_id = created.json()["receipt"]["public_id"]
    action, fields = _form(browser, kind, public_id=public_id)
    assert json.loads(fields["draft_scope"]) == scope
    return browser, action, fields, scope, headers

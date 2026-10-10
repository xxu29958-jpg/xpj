"""Installed planning forms retain the original receipt and reject rebinding."""
import json

import pytest
from _web_recurring_test_support import open_recurring_form
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    Budget,
    BudgetCategory,
    BudgetRevision,
    Expense,
    LedgerMember,
    MonthlyArrangement,
    MonthlyArrangementRevision,
    RecurringItem,
    RecurringItemRevision,
    RecurringOccurrence,
    RecurringOccurrenceRevision,
)
from app.services.identity_service import authenticate_web_session_token
from app.services.manual_expense_draft_presenter import manual_draft_scope
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_manual_expense import _hidden_fields
from tests.test_web_recurring_occurrences import _choose

KINDS = ["budget", "arrangement", "recurring-create", "recurring-edit"]
MONTH = "2026-09"


@pytest.fixture
def installed_planning_browser():
    yield from installed_web_setup()


def _scope(token):
    with SessionLocal() as db:
        return manual_draft_scope(db, authenticate_web_session_token(db, token, ttl_seconds=8 * 60 * 60).auth)


def _facts():
    with SessionLocal() as db:
        return [list(db.execute(select(*model.__table__.columns).order_by(model.id))) for model in
            [Budget, BudgetCategory, BudgetRevision, MonthlyArrangement, MonthlyArrangementRevision, RecurringItem, RecurringItemRevision, Expense,
             RecurringOccurrence, RecurringOccurrenceRevision]]


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


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_occurrence_original_receipt_survives_unlink_and_rejects_readonly_or_replacement_identity(installed_planning_browser):
    installed = installed_planning_browser
    browser, action, fields, scope, headers = _original(installed, "recurring-create")
    created = browser.post(action, data=fields, headers=headers)
    assert created.status_code == 200, created.text
    series_id = created.json()["receipt"]["public_id"]
    manual_page = browser.get("/web/expenses/new")
    manual = {**_hidden_fields(manual_page.text), "amount_major": "15.00", "currency_code": "CNY",
        "merchant": "跨月付款", "category": "餐饮", "spent_at": "2026-08-31T12:00", "note": "原付款"}
    payment = browser.post("/web/expenses/new", data=manual, headers={"Origin": headers["Origin"]}, follow_redirects=False)
    assert payment.status_code == 303, payment.text
    path = f"/web/recurring/{series_id}/occurrence"
    page = browser.get(path, params={"month": MONTH, "payment_month": "2026-08", "q": "跨月"})
    original = _choose(browser, page.text, "link")
    assert original["month"] == MONTH and original["payment_month"] == "2026-08" and original["q"] == "跨月"
    before = _facts()
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == scope["ledgerId"],
            LedgerMember.account_id == installed.installation_account_id))
        member.role = "viewer"
        db.commit()
    refused = browser.post(path, data=original, headers=headers)
    assert refused.status_code == 403 and _facts() == before, refused.text
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == scope["ledgerId"],
            LedgerMember.account_id == installed.installation_account_id))
        member.role = "member"
        db.commit()
    accepted = browser.post(path, data=original, headers=headers)
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    assert result["ack"] == {"scope": scope, "clientRef": original["idempotency_key"]}
    assert result["receipt"]["expense_public_id"] == original["expense_public_id"]
    current = browser.get(result["next"])
    assert 'name="payment_month" value="2026-08"' in current.text and 'name="q" value="跨月"' in current.text
    clear = _choose(browser, current.text, "clear")
    cleared = browser.post(path, data=clear, headers=headers)
    assert cleared.status_code == 200 and cleared.json()["receipt"]["expense_public_id"] is None, cleared.text
    after = _facts()
    replay = browser.post(path, data=original, headers=headers)
    assert replay.status_code == 200 and replay.json() == result, replay.text
    assert _facts() == after, "Original replay must not relink or alter the payment after an explicit unlink"
    browser.base_url = browser.base_url.copy_with(scheme="http")
    replacement = _scope(_connect_local_session(installed))
    browser.base_url = browser.base_url.copy_with(scheme="https")
    assert replacement["deviceId"] != scope["deviceId"]
    fresh = _choose(browser, browser.get(result["next"]).text, "link")
    original["csrf_token"] = fresh["csrf_token"]
    for review in (False, True):
        refused = browser.post(path, data={**original, **({"review_latest": "true"} if review else {})}, headers=headers)
        assert refused.status_code == 409 and refused.json()["error"] == "session_binding_changed", refused.text
    assert _facts() == after


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
@pytest.mark.parametrize("kind", KINDS)
def test_original_planning_receipt_replays_after_another_revision_without_rewriting_it(installed_planning_browser, kind):
    browser, action, fields, scope, headers = _original(installed_planning_browser, kind)
    accepted = browser.post(action, data=fields, headers=headers, follow_redirects=False)
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()
    assert result["ack"] == {"scope": scope, "clientRef": fields["idempotency_key"]}
    receipt = result["receipt"]
    assert receipt["ledger_id"] == scope["ledgerId"] and receipt["home_currency_code"] == "CNY"
    amount_field = {"budget": "total_amount_cents", "arrangement": "savings_target_cents"}.get(kind, "baseline_amount_cents")
    assert receipt[amount_field] == 1500
    if kind == "budget":
        assert "/web/categories?" in result["next"] and receipt["rollover_amount_cents"] == -100
        assert [(row["category"], row["amount_cents"]) for row in receipt["category_budgets"]] == [("餐饮", 500)]
    later_kind = "recurring-edit" if kind.startswith("recurring") else kind
    later_action, later = _form(browser, later_kind, public_id=receipt.get("public_id", ""), amount="40.00")
    assert later["idempotency_key"] != fields["idempotency_key"]
    changed = browser.post(later_action, data=later, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["receipt"][amount_field] == 4000
    assert changed.json()["receipt"]["row_version"] == receipt["row_version"] + 1
    after = _facts()
    replayed = browser.post(action, data=fields, headers=headers)
    assert replayed.status_code == 200 and replayed.json() == result, replayed.text
    assert _facts() == after, "An old browser retry must return its original receipt without rewriting later facts"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 0, "Planning does not create a payment"
        if kind != "budget":
            assert db.scalar(select(func.count()).select_from(Budget)) == 0


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
@pytest.mark.parametrize("kind", KINDS)
def test_original_planning_intent_survives_readonly_but_cannot_follow_a_replacement_browser(installed_planning_browser, kind):
    installed = installed_planning_browser
    browser, action, fields, scope, headers = _original(installed, kind)
    before = _facts()
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == installed.shared_ledger_id,
            LedgerMember.account_id == installed.installation_account_id))
        member.role = "viewer"
        db.commit()
    refused = browser.post(action, data=fields, headers=headers)
    assert refused.status_code == 403, refused.text
    assert _facts() == before
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == installed.shared_ledger_id,
            LedgerMember.account_id == installed.installation_account_id))
        member.role = "member"
        db.commit()
    accepted = browser.post(action, data=fields, headers=headers)
    assert accepted.status_code == 200 and accepted.json()["ack"]["clientRef"] == fields["idempotency_key"], accepted.text
    after = _facts()
    browser.base_url = browser.base_url.copy_with(scheme="http")
    replacement = _scope(_connect_local_session(installed))
    browser.base_url = browser.base_url.copy_with(scheme="https")
    assert replacement["deviceId"] != scope["deviceId"] and replacement["ledgerId"] == scope["ledgerId"]
    _, fresh = _form(browser, "recurring-edit" if kind.startswith("recurring") else kind,
        public_id=accepted.json()["receipt"].get("public_id", ""))
    fields["csrf_token"] = fresh["csrf_token"]
    for review in (False, True):
        refused = browser.post(action, data={**fields, **({"review_latest": "true"} if review else {})}, headers=headers)
        assert refused.status_code == 409 and refused.json()["error"] == "session_binding_changed", refused.text
    assert _facts() == after


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
@pytest.mark.parametrize("kind", KINDS)
def test_older_native_planning_form_requires_explicit_non_writing_identity_review(installed_planning_browser, kind):
    browser, action, fields, scope, headers = _original(installed_planning_browser, kind)
    fields.pop("draft_scope")
    before = _facts()
    native_headers = {"Origin": headers["Origin"]}
    refused = browser.post(action, data=fields, headers=native_headers)
    assert refused.status_code == 409, refused.text
    assert _facts() == before and "15.00" in refused.text
    assert 'name="review_latest"' in refused.text
    reviewed = browser.post(action, data={**fields, "review_latest": "true"}, headers=native_headers)
    assert reviewed.status_code == 200, reviewed.text
    assert _facts() == before, "Review may prepare input but must not create or edit a financial plan"
    form_action = "/web/budget-advise" if kind == "arrangement" else action
    prepared = {**fields, **hidden_post_forms(reviewed.text)[form_action]}
    assert json.loads(prepared["draft_scope"]) == scope
    accepted = browser.post(action, data=prepared, headers=headers)
    assert accepted.status_code == 200 and accepted.json()["ack"]["scope"] == scope, accepted.text

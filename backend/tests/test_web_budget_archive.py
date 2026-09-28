"""The budget consumer can retire an arrangement without losing its financial facts."""
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Budget, BudgetCategory, BudgetRevision, Expense
from tests._local_web_identity_support import installed_web_setup
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_planning_bound_intents import MONTH, _original


@pytest.fixture
def installed_budget_browser():
    yield from installed_web_setup()


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_budget_page_can_archive_its_captured_version_and_retains_history(installed_budget_browser):
    browser, action, fields, _, headers = _original(installed_budget_browser, "budget")
    browser.headers.update({"Origin": headers["Origin"]})
    saved = browser.post(action, data=fields, headers=headers)
    assert saved.status_code == 200, saved.text
    page = browser.get("/web/budgets", params={"month": MONTH})
    forms = hidden_post_forms(page.text)
    assert "/web/budgets/archive" in forms, "A configured budget has no usable archive entry"
    original = forms["/web/budgets/archive"]
    assert original["month"] == MONTH
    assert int(original["expected_row_version"]) == saved.json()["receipt"]["row_version"]
    archived = browser.post("/web/budgets/archive", data=original, follow_redirects=False)
    assert archived.status_code == 303, archived.text
    with SessionLocal() as db:
        budget = db.scalar(select(Budget))
        assert budget.archived_at is not None
        assert budget.total_amount_cents == 1500
        revisions = list(db.scalars(select(BudgetRevision).order_by(BudgetRevision.id)))
        assert [row.change_kind for row in revisions] == ["create", "archive"]
        assert not list(db.scalars(select(Expense)))
        assert list(db.scalars(select(BudgetCategory)))
    # The old confirmation is not permission to archive a subsequently restored version.
    recycle = browser.get("/web/recycle-bin")
    restore = hidden_post_forms(recycle.text)["/web/recycle-bin/restore"]
    assert restore["resource_id"] == MONTH and restore["kind"] == "monthly_budget"
    restored = browser.post("/web/recycle-bin/restore", data=restore, follow_redirects=False)
    assert restored.status_code == 303, restored.text
    stale = browser.post("/web/budgets/archive", data=original, follow_redirects=False)
    assert stale.status_code == 409, stale.text
    with SessionLocal() as db:
        assert db.scalar(select(Budget)).archived_at is None

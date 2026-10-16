"""The pending review consumes the existing score writer and original draft protocol."""
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.responses import FileResponse

from app.models import Expense
from tests import test_web_expense_review_runtime as review_tests
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store
from tests.web_expense_fact_test_support import confirmation_web as confirmation_web

review_browser = review_tests.review_browser


@pytest.fixture
def score_browser(review_browser, confirmation_store):
    client, scope = review_browser
    with confirmation_store() as db:
        current = db.get(Expense, 42)
        current.value_score, current.regret_score = 4, 3
        db.commit()

    @client.app.get("/score-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/review_scores_probe.js", media_type="text/javascript")

    client.app.state.expense_review_probe = "score-probe.js"
    return client, scope, confirmation_store


def _fields(scope, **scores):
    return {"ledger_id": "owner", "expected_row_version": "4", "idempotency_key": str(uuid4()),
        "draft_ref": str(uuid4()), "draft_scope": json.dumps(scope), "merchant": "原评分商家",
        "amount_yuan": "2850", "original_currency": "JPY", "category": "购物", "save_before_confirm": "1", **scores}


@pytest.mark.parametrize("action", ["save", "confirm"])
def test_review_score_clear_and_value_share_original_acceptance(score_browser, action):
    client, scope, session_factory = score_browser
    fields = _fields(scope, value_score="", regret_score="5")
    path = f"/web/expenses/42/{action}"
    first = client.post(path, data=fields, headers={"Accept": "application/json"})
    assert first.status_code == 200, first.text
    with session_factory() as db:
        current = db.get(Expense, 42)
        assert (current.value_score, current.regret_score, current.status) == (None, 5, "pending" if action == "save" else "confirmed")
        current.value_score, current.regret_score, current.row_version = 2, 2, current.row_version + 1
        db.commit()
    replay = client.post(path, data=fields, headers={"Accept": "application/json"})
    assert replay.json() == first.json()
    with session_factory() as db:
        assert (db.get(Expense, 42).value_score, db.get(Expense, 42).regret_score) == (2, 2)


def test_invalid_score_rejects_all_changes_and_preserves_original_native_form(score_browser):
    client, scope, session_factory = score_browser
    fields = _fields(scope, value_score="6", regret_score="")
    rejected = client.post("/web/expenses/42/save", data=fields)
    assert rejected.status_code == 422, rejected.text
    assert "原评分商家" in rejected.text and fields["idempotency_key"] in rejected.text
    assert 'name="expected_row_version" value="4"' in rejected.text
    with session_factory() as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.value_score, current.regret_score) == ("首次便利店", 4, 4, 3)


@pytest.mark.parametrize("entry", ["full", "drawer"])
def test_score_choice_and_clear_resume_in_real_review_before_original_save(score_browser, tmp_path, entry):
    client, _, session_factory = score_browser
    path = "/web/pending?ledger_id=owner" if entry == "drawer" else "/web/expenses/42/edit?ledger_id=owner&return_to=pending"
    result = review_tests._run_review_page(client, tmp_path, path)
    assert not result.get("error"), result
    assert result["resumed"] and result["first"] == result["replay"]
    with session_factory() as db:
        current = db.get(Expense, 42)
        assert (current.status, current.value_score, current.regret_score, current.merchant) == ("pending", None, 5, "原评分填写")

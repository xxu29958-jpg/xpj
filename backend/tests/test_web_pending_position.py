"""Full review reads its position from the same scoped, filtered queue as the inbox."""

import re
from uuid import uuid4

import pytest

from app.models import Expense
from tests import _web_expense_review_test_support as review
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store
from tests.web_expense_fact_test_support import confirmation_web as confirmation_web

review_browser = review.review_browser


@pytest.fixture
def queue_browser(review_browser, confirmation_store):
    with confirmation_store() as db:
        original = db.get(Expense, 42)
        values = {column.name: getattr(original, column.name) for column in Expense.__table__.columns
                  if column.name not in {"id", "public_id"}}
        for identity, changes in [(40, {}), (43, {"amount_cents": None, "original_amount_minor": None}),
                                  (44, {"status": "rejected"}), (45, {"tenant_id": "tester_1"})]:
            db.add(Expense(**{**values, **changes}, id=identity, public_id=str(uuid4())))
        db.commit()
    return review_browser[0]


@pytest.mark.parametrize("filter_key,expected", [("all", [43, 42, 40]), ("ready", [42, 40]),
                                                ("missing_amount", [43])])
def test_full_review_position_matches_the_filtered_inbox(queue_browser, filter_key, expected):
    listing = queue_browser.get("/web/pending", params={"ledger_id": "owner", "filter": filter_key})
    assert listing.status_code == 200
    assert [int(value) for value in re.findall(r'data-expense-id="(\d+)"', listing.text)] == expected
    for position, identity in enumerate(expected, 1):
        page = queue_browser.get(f"/web/expenses/{identity}/edit", params={"ledger_id": "owner",
            "return_to": "pending", "return_filter": filter_key})
        assert page.status_code == 200
        assert f"第 {position} / {len(expected)} 张" in page.text


def test_queue_position_refreshes_and_does_not_relabel_an_original_task(queue_browser, confirmation_store):
    path = "/web/expenses/42/edit?ledger_id=owner&return_to=pending&return_filter=ready"
    assert "第 1 / 2 张" in queue_browser.get(path).text
    with confirmation_store() as db:
        db.get(Expense, 40).status = "rejected"
        db.commit()
    assert "第 1 / 1 张" in queue_browser.get(path).text
    assert "data-review-position" not in queue_browser.get(path.replace("ready", "missing_amount")).text
    assert "data-review-position" not in queue_browser.get(path.replace("pending", "search")).text
    with confirmation_store() as db:
        db.get(Expense, 42).status = "confirmed"
        db.commit()
    original = queue_browser.get(path + "&confirmation_task=1")
    assert original.status_code == 200
    assert "data-review-position" not in original.text

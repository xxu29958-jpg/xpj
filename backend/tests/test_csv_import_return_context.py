from urllib.parse import parse_qs, urlsplit

import pytest

from app.routes._web_expense_return_context import (
    ExpenseReturnContext,
    confirm_return_redirect,
    edit_navigation_view,
    flow_href,
)

_BATCH = "339b49f5-7d71-4cc5-9c75-2d941f2a1d45"


def test_confirm_and_edit_return_to_the_original_csv_event_task():
    context = ExpenseReturnContext(return_to="csv_import_event", return_import_public_id=_BATCH,
        return_import_line_number="7")
    target = f"/web/import/{_BATCH}/rows/7/review"
    path, params = confirm_return_redirect(context)
    assert (path, params) == (target, {})
    view = edit_navigation_view(context, expense_id=42, ledger_id="family")
    assert view["edit_return_href"] == target + "?ledger_id=family"
    assert view["edit_return_fields"] == {"return_to": "csv_import_event",
        "return_import_public_id": _BATCH, "return_import_line_number": "7"}
    next_link = flow_href("/web/expenses/42/correction", ledger_id="family", **context.as_kwargs())
    assert parse_qs(urlsplit(next_link).query)["return_import_line_number"] == ["7"]


@pytest.mark.parametrize(("batch", "line"), [("../../owner", "7"), (_BATCH, "../1"), (_BATCH, "0")])
def test_invalid_csv_origin_cannot_become_a_redirect_path(batch, line):
    context = ExpenseReturnContext(return_to="csv_import_event", return_import_public_id=batch,
        return_import_line_number=line)
    assert confirm_return_redirect(context) == ("/web/pending", {})
    assert edit_navigation_view(context, expense_id=42, ledger_id="family")["edit_return_fields"] == {}


def test_confirm_returns_to_the_explicitly_selected_import_root():
    context = ExpenseReturnContext(return_to="csv_import_event", return_import_public_id=_BATCH,
        return_import_line_number="7", return_import_expense_id="42")
    target = f"/web/import/{_BATCH}/rows/7/review"
    assert confirm_return_redirect(context) == (target, {"expense_id": "42"})
    view = edit_navigation_view(context, expense_id=42, ledger_id="family")
    assert parse_qs(urlsplit(view["edit_return_href"]).query)["expense_id"] == ["42"]
    assert view["edit_return_fields"]["return_import_expense_id"] == "42"

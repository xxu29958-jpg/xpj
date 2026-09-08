"""Budget raw input, captured currency and retry identity survive a refusal."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import AppError
from app.routes.web_budgets import _budget_payload_from_draft
from app.services import budget_command_service as command


def _draft(**changes):
    return dict(home_currency_code="JPY", expected_row_version="null", total_amount_yuan="1200",
        rollover_amount_yuan="-20", non_monthly_amount_yuan="", excluded_category=[], excluded_categories="",
        category_budget_category=["食事"], category_budget_amount_yuan=["100"], category_budget_remove=set(), **changes)


def test_budget_form_parses_captured_jpy_without_a_default_currency():
    draft = _draft()
    body = _budget_payload_from_draft(draft)
    assert body.home_currency_code == "JPY" and body.total_amount_cents == 1200
    assert body.expected_row_version is None and body.rollover_amount_cents == -20
    assert body.category_budgets[0].amount_cents == 100
    assert draft["total_amount_yuan"] == "1200"


@pytest.mark.parametrize("version", ["", "0", "yesterday"])
def test_budget_form_never_treats_an_invalid_version_as_unconfigured(version):
    draft = _draft()
    draft["expected_row_version"] = version
    with pytest.raises(AppError, match="预算版本无法确认"):
        _budget_payload_from_draft(draft)


def test_pending_save_cannot_be_replaced_by_a_new_review_key():
    db = Mock()
    db.scalar.return_value = SimpleNamespace(operation="save_monthly_budget", target_type="monthly_budget",
        target_id="2026-09", status="in_progress")
    with pytest.raises(AppError) as exc:
        command.review_monthly_budget_save(db, tenant_id="owner", month="2026-09", idempotency_key="original-key")
    assert exc.value.error == "idempotency_key_in_progress"
    db.commit.assert_not_called()


def test_review_keeps_an_unresolved_original_key_when_no_receipt_exists():
    db = Mock()
    db.scalar.return_value = None
    assert command.review_monthly_budget_save(db, tenant_id="owner", month="2026-09", idempotency_key="original-key") is False
    db.commit.assert_not_called()

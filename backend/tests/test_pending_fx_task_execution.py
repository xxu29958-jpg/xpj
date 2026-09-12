"""Small execution-boundary checks; actual bill/worker integration lives alongside these."""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree.ElementTree import ParseError

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import BackgroundTask, Expense
from app.services import expense_split_service, receipt_item_service
from app.services import pending_fx_task_service as service
from app.services.background_task_handler_api import TaskCancelledError
from app.services.expense_service import _fx
from app.services.expense_service._fx import PendingFxInput, PendingFxResult
from app.services.fx_rate_provider import EcbDailyRates, FxFetchError


@pytest.fixture
def execution(monkeypatch):
    original = PendingFxInput(expense_id=7, tenant_id="owner", expected_row_version=2,
        home_currency_code="CNY", original_currency_code="USD", original_amount_minor=1000,
        rate_date=date(2026, 5, 31))
    task = BackgroundTask(id=11, task_type="expense_fx", tenant_id="owner", source_expense_id=7,
        status="running", input_payload_json=original.model_dump_json())
    db = Mock(spec=Session)
    db.get.return_value = task
    monkeypatch.setattr(service, "check_cancellation_requested", Mock(return_value=False))
    monkeypatch.setattr(service, "check_pending_fx", Mock(return_value=Expense(id=7)))
    monkeypatch.setattr(service, "resolve_payload_rate", Mock(return_value=(None, None, "pending", original.rate_date)))
    monkeypatch.setattr(service, "apply_pending_fx", Mock(return_value=PendingFxResult(7, "updated", 3)))
    monkeypatch.setattr(service, "mark_failed", Mock())
    return db, task, original


def test_network_has_no_preflight_transaction_and_result_is_staged_before_commit(execution, monkeypatch):
    db, task, original = execution
    daily = EcbDailyRates(date(2026, 5, 29), {"EUR": Decimal(1), "USD": Decimal(1), "CNY": Decimal(7)})

    def fetch(saved):
        assert saved == original
        db.rollback.assert_called_once_with()
        assert task.result_summary_json is None
        return daily

    def commit():
        assert json.loads(task.result_summary_json) == {"expense_id": 7, "outcome": "updated", "row_version": 3}
        service.apply_pending_fx.assert_called_once_with(db, original, daily)
        assert task.progress_current == task.progress_total == 1

    monkeypatch.setattr(service, "fetch_pending_fx_reference", fetch)
    db.commit.side_effect = commit
    service.run_pending_expense_fx_task(db, task, {"expense_id": 999, "rate_date": "today"})
    db.commit.assert_called_once_with()
    service.mark_failed.assert_not_called()


def test_covered_cache_avoids_provider_and_saved_result_avoids_reexecution(execution, monkeypatch):
    db, task, original = execution
    fetch = Mock(side_effect=AssertionError("covered/manual rate must not fetch"))
    monkeypatch.setattr(service, "fetch_pending_fx_reference", fetch)
    monkeypatch.setattr(service, "resolve_payload_rate", Mock(return_value=(Decimal(7), "manual", "ready", original.rate_date)))
    service.run_pending_expense_fx_task(db, task, {})
    service.run_pending_expense_fx_task(db, task, {})
    service.check_pending_fx.assert_called_once_with(db, original)
    service.apply_pending_fx.assert_called_once_with(db, original, None)
    db.commit.assert_called_once_with()
    fetch.assert_not_called()


@pytest.mark.parametrize("error", [FxFetchError("https://configured.private/rates?secret=example"),
    ValueError("private parse content"), ParseError("private XML content"),
    TypeError("private result content"), ArithmeticError("private amount content"),
    SQLAlchemyError("SELECT private_storage_details")])
def test_failure_is_rolled_back_and_never_publishes_provider_or_sql_details(execution, monkeypatch, error):
    db, task, _ = execution
    monkeypatch.setattr(service, "fetch_pending_fx_reference", Mock(side_effect=error))
    service.run_pending_expense_fx_task(db, task, {})
    assert db.rollback.call_count == 2
    db.commit.assert_not_called()
    service.apply_pending_fx.assert_not_called()
    failure = service.mark_failed.call_args.kwargs
    assert failure["error_code"] in {"fx_reference_unavailable", "fx_storage_unavailable"}
    assert str(error) not in failure["error_message"]
    assert "账单已保留" in failure["error_message"]
    assert task.result_summary_json is None


def test_cancellation_after_fetch_preserves_original_and_is_not_a_failure(execution, monkeypatch):
    db, task, _ = execution
    monkeypatch.setattr(service, "check_cancellation_requested", Mock(side_effect=[False, True]))
    monkeypatch.setattr(service, "fetch_pending_fx_reference", Mock(return_value=object()))
    with pytest.raises(TaskCancelledError):
        service.run_pending_expense_fx_task(db, task, {})
    service.apply_pending_fx.assert_not_called()
    service.mark_failed.assert_not_called()
    db.commit.assert_not_called()


def test_input_cannot_be_rebound_to_a_different_source_or_ledger(execution):
    db, task, _ = execution
    task.tenant_id = "other-ledger"
    service.run_pending_expense_fx_task(db, task, {})
    service.check_pending_fx.assert_not_called()
    service.mark_failed.assert_called_once()
    assert task.result_summary_json is None


def test_commit_ack_loss_keeps_accepted_result_for_worker_completion(execution, monkeypatch):
    db, task, original = execution
    monkeypatch.setattr(service, "resolve_payload_rate", Mock(return_value=(Decimal(7), "manual", "ready", original.rate_date)))
    db.commit.side_effect = SQLAlchemyError("response lost after actual COMMIT")
    service.run_pending_expense_fx_task(db, task, {})
    assert json.loads(task.result_summary_json)["outcome"] == "updated"
    service.mark_failed.assert_not_called()


def test_unavailable_error_storage_still_raises_only_a_safe_message(execution, monkeypatch):
    db, task, _ = execution
    monkeypatch.setattr(service, "fetch_pending_fx_reference", Mock(side_effect=FxFetchError("private endpoint")))
    service.mark_failed.side_effect = SQLAlchemyError("INSERT private_db_row")
    with pytest.raises(service.PendingFxTaskError, match="原账单已保留") as failure:
        service.run_pending_expense_fx_task(db, task, {})
    assert "private" not in str(failure.value)


def test_conflict_receipt_cannot_satisfy_the_users_new_version(execution):
    _, task, original = execution
    task.result_summary_json = json.dumps({"expense_id": original.expense_id,
        "outcome": "conflict", "row_version": original.expected_row_version + 1})
    assert service._matches_committed_result(task, original, original.expected_row_version)
    assert not service._matches_committed_result(task, original, original.expected_row_version + 1)


@pytest.mark.parametrize("outcome,current_version,visible", [
    (None, 2, True), (None, 3, False), ("updated", 3, True), ("updated", 4, False), ("conflict", 3, False),
])
def test_current_task_projection_excludes_old_inputs_and_only_associates_applied_results(
    execution, monkeypatch, outcome, current_version, visible,
):
    db, task, original = execution
    if outcome is not None:
        task.result_summary_json = json.dumps({"expense_id": original.expense_id,
            "outcome": outcome, "row_version": 3})
    lookup = Mock(return_value={original.expense_id: task})
    monkeypatch.setattr(service, "latest_pending_expense_fx_tasks", lookup)
    expense = Expense(id=original.expense_id, tenant_id=original.tenant_id, row_version=current_version)
    foreign = Expense(id=999, tenant_id="other", row_version=2)
    projected = service.current_pending_expense_fx_tasks(db, tenant_id="owner", expenses=[expense, foreign])
    assert projected == ({expense.id: task} if visible else {})
    lookup.assert_called_once_with(db, tenant_id="owner", expense_ids=[expense.id])


@pytest.fixture
def pending_conversion(monkeypatch):
    expense = Expense(id=7, tenant_id="owner", status="pending", row_version=2, home_currency_code="CNY",
        original_currency_code="USD", original_amount_minor=1000, exchange_rate_date=date(2026, 5, 4),
        fx_status="pending", items_sum_status="matched")
    original = PendingFxInput.from_expense(expense)
    monkeypatch.setattr(_fx, "check_pending_fx", lambda *a, **kw: expense)
    monkeypatch.setattr(_fx, "resolve_write_capability", lambda *a: None)
    monkeypatch.setattr(_fx, "resolve_payload_rate", lambda *a, **kw: (Decimal(7), "manual", "ready", original.rate_date))
    monkeypatch.setattr(_fx, "mark_duplicate_status", lambda *a: None)
    monkeypatch.setattr(_fx, "bump_row_version", lambda row: setattr(row, "row_version", row.row_version + 1))
    monkeypatch.setattr(receipt_item_service, "_compute_items_sum_cents", lambda *a: 6500)
    monkeypatch.setattr(expense_split_service, "_expense_splits", lambda *a, **kw: [])
    return Mock(spec=Session), expense, original


def test_conversion_reconciles_existing_receipt_items_with_the_new_parent_amount(pending_conversion):
    db, expense, original = pending_conversion
    result = _fx.apply_pending_fx(db, original, None)
    assert expense.amount_cents == 7000 and expense.items_sum_status == "mismatch_known"
    assert expense.status == "pending" and result.row_version == 3


def test_conversion_cannot_publish_a_parent_below_its_existing_split_allocation(pending_conversion, monkeypatch):
    from app.errors import AppError

    db, expense, original = pending_conversion
    monkeypatch.setattr(expense_split_service, "_expense_splits", lambda *a, **kw: [SimpleNamespace(amount_cents=8000)])
    with pytest.raises(AppError) as refused:
        _fx.apply_pending_fx(db, original, None)
    assert refused.value.error == "expense_split_total_exceeds_parent"
    assert expense.row_version == original.expected_row_version
    db.commit.assert_not_called()

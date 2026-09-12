"""Real persisted bill, task admission and worker continuation counterexamples."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.auth import get_current_writer_context
from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask, Device, Expense, LedgerMember
from app.services import background_task_service, background_task_worker
from app.services import pending_fx_task_service as service
from app.services.background_task_admission import BackgroundTaskCapacityFullError
from app.services.currency_binding_service import resolve_write_capability
from app.services.fx_rate_provider import EcbDailyRates, FxFetchError, upsert_fx_rate
from app.services.identity_service import authenticate_session_token
from app.services.optimistic_concurrency import bump_row_version

pytestmark = pytest.mark.real_db
REQUESTED_DATE = date(2026, 5, 31)
PUBLICATION_DATE = date(2026, 5, 29)


def _seed_pending_task(identity):
    with SessionLocal() as db:
        auth = authenticate_session_token(db, identity.app_token, {"app"})
        resolve_write_capability(db)
        expense = Expense(tenant_id=auth.tenant_id, status="pending", category="交通", source="CSV导入",
            home_currency_code="CNY", original_currency_code="USD", original_amount_minor=1000,
            amount_cents=None, fx_status="pending", exchange_rate_source=None, exchange_rate_to_cny=None,
            exchange_rate_date=REQUESTED_DATE, expense_time=datetime(2026, 5, 31, 4, tzinfo=UTC))
        db.add(expense)
        db.flush()
        prepared = service.prepare_pending_expense_fx(db, expense=expense,
            initiator_account_id=auth.account_id, initiator_device_id=auth.device_id)
        assert prepared is not None
        db.commit()
        return expense.id, expense.row_version, prepared.task_id, auth


def _daily():
    return EcbDailyRates(PUBLICATION_DATE, {"EUR": Decimal(1), "USD": Decimal(1), "CNY": Decimal(7)})


def _run(task_id):
    # Process-local payload is deliberately empty: the durable original owns execution.
    background_task_worker.run_task(task_id, {})


def test_dated_provider_revises_pending_bill_once_and_releases_read_transaction(identity, monkeypatch):
    expense_id, version, task_id, _ = _seed_pending_task(identity)
    checked_sessions = []
    original_check = service.check_pending_fx

    def check(db, original):
        checked_sessions.append(db)
        return original_check(db, original)

    def fetch(original):
        assert original.rate_date == REQUESTED_DATE
        assert original.original_currency_code == "USD"
        assert not checked_sessions[-1].in_transaction()
        return _daily()

    monkeypatch.setattr(service, "check_pending_fx", check)
    provider = Mock(side_effect=fetch)
    monkeypatch.setattr(service, "fetch_pending_fx_reference", provider)
    _run(task_id)
    _run(task_id)
    with SessionLocal() as db:
        expense, task = db.get(Expense, expense_id), db.get(BackgroundTask, task_id)
        assert (expense.status, expense.fx_status, expense.amount_cents) == ("pending", "ready", 7000)
        assert expense.exchange_rate_date == PUBLICATION_DATE
        assert expense.row_version == version + 1 and expense.confirmed_at is None
        assert task.status == "completed" and task.source_expense_id == expense_id
        assert json.loads(task.result_summary_json) == {
            "expense_id": expense_id, "outcome": "updated", "row_version": version + 1,
        }
        assert service.latest_pending_expense_fx_tasks(db, tenant_id="owner", expense_ids=[expense_id]) == {expense_id: task}
        assert service.latest_pending_expense_fx_tasks(db, tenant_id="tester_1", expense_ids=[expense_id]) == {}
    provider.assert_called_once()


def test_available_exact_cache_updates_pending_without_network(identity, monkeypatch):
    expense_id, version, task_id, _ = _seed_pending_task(identity)
    with SessionLocal() as db:
        upsert_fx_rate(db, currency_code="USD", home_currency_code="CNY", rate_date=REQUESTED_DATE,
            rate_to_home=Decimal(7))
        db.commit()
    provider = Mock(side_effect=AssertionError("Exact dated cache should be consumed first"))
    monkeypatch.setattr(service, "fetch_pending_fx_reference", provider)
    _run(task_id)
    with SessionLocal() as db:
        expense, task = db.get(Expense, expense_id), db.get(BackgroundTask, task_id)
        assert (expense.status, expense.amount_cents, expense.row_version) == ("pending", 7000, version + 1)
        assert task.status == "completed"
    provider.assert_not_called()


def test_cached_preflight_cannot_hide_an_edit_before_the_apply_lock(identity, monkeypatch):
    expense_id, version, task_id, _ = _seed_pending_task(identity)
    with SessionLocal() as db:
        upsert_fx_rate(db, currency_code="USD", home_currency_code="CNY", rate_date=REQUESTED_DATE,
            rate_to_home=Decimal(7))
        db.commit()
    original_apply = service.apply_pending_fx

    def edit_before_apply(db, original, daily):
        with SessionLocal() as user_db:
            resolve_write_capability(user_db)
            expense = user_db.get(Expense, expense_id)
            expense.original_amount_minor = 2000
            bump_row_version(expense)
            user_db.commit()
        return original_apply(db, original, daily)

    monkeypatch.setattr(service, "apply_pending_fx", edit_before_apply)
    _run(task_id)
    with SessionLocal() as db:
        expense, task = db.get(Expense, expense_id), db.get(BackgroundTask, task_id)
        assert (expense.fx_status, expense.amount_cents, expense.original_amount_minor) == ("pending", None, 2000)
        assert expense.row_version == version + 1
        assert task.status == "completed" and json.loads(task.result_summary_json)["outcome"] == "conflict"


def test_provider_failure_preserves_original_and_only_explicit_retry_creates_another_task(identity, monkeypatch):
    expense_id, version, task_id, auth = _seed_pending_task(identity)
    monkeypatch.setattr(service, "fetch_pending_fx_reference", Mock(side_effect=FxFetchError("https://private?key=hidden")))
    _run(task_id)
    monkeypatch.setattr(background_task_service, "_submit_task", Mock())
    with SessionLocal() as db:
        expense, task = db.get(Expense, expense_id), db.get(BackgroundTask, task_id)
        original_payload = task.input_payload_json
        assert (expense.fx_status, expense.amount_cents, expense.row_version) == ("pending", None, version)
        assert task.status == "failed" and task.error_code == "fx_reference_unavailable"
        assert "private" not in task.error_message and "hidden" not in task.error_message
        assert service.prepare_pending_expense_fx(db, expense=expense,
            initiator_account_id=auth.account_id, initiator_device_id=auth.device_id) is None
        retried = service.request_pending_expense_fx(db, tenant_id=auth.tenant_id,
            initiator_account_id=auth.account_id, initiator_device_id=auth.device_id,
            expense_id=expense_id, expected_row_version=version)
        assert retried.id != task_id and retried.input_payload_json == original_payload
        repeated = service.request_pending_expense_fx(db, tenant_id=auth.tenant_id,
            initiator_account_id=auth.account_id, initiator_device_id=None,
            expense_id=expense_id, expected_row_version=version)
        assert repeated.id == retried.id
        assert db.scalar(select(func.count()).select_from(BackgroundTask).where(
            BackgroundTask.source_expense_id == expense_id)) == 2


def test_restart_after_result_commit_completes_original_despite_later_edit(identity, monkeypatch):
    expense_id, version, task_id, auth = _seed_pending_task(identity)
    provider = Mock(return_value=_daily())
    monkeypatch.setattr(service, "fetch_pending_fx_reference", provider)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        task.status = "running"
        db.commit()
        service.run_pending_expense_fx_task(db, task, {})
        committed = task.result_summary_json
        assert task.status == "running" and json.loads(committed)["outcome"] == "updated"
        resolve_write_capability(db)
        expense = db.get(Expense, expense_id)
        expense.merchant = "later user edit"
        bump_row_version(expense)
        db.commit()
    assert background_task_service.recover_orphaned_tasks() >= 1
    monkeypatch.setattr(background_task_service, "_submit_task",
        lambda task_id, payload, *, registry: background_task_worker.run_task(task_id, payload, registry))
    with SessionLocal() as db:
        original = service.request_pending_expense_fx(db, tenant_id=auth.tenant_id,
            initiator_account_id=auth.account_id, initiator_device_id=auth.device_id,
            expense_id=expense_id, expected_row_version=version)
        assert original.id == task_id
    with SessionLocal() as db:
        task, expense = db.get(BackgroundTask, task_id), db.get(Expense, expense_id)
        assert task.status == "completed" and task.result_summary_json == committed
        assert (expense.status, expense.row_version, expense.merchant) == ("pending", version + 2, "later user edit")
    provider.assert_called_once()


@pytest.mark.parametrize("interruption", ["edit", "cancel"])
def test_user_change_or_cancellation_during_provider_preserves_bill(identity, monkeypatch, interruption):
    expense_id, version, task_id, _ = _seed_pending_task(identity)

    def fetch(_original):
        with SessionLocal() as db:
            if interruption == "cancel":
                task = db.get(BackgroundTask, task_id)
                background_task_service.request_cancellation(db, task.public_id, account_id=None, tenant_id=None)
            else:
                resolve_write_capability(db)
                expense = db.get(Expense, expense_id)
                expense.original_amount_minor = 2000
                bump_row_version(expense)
                db.commit()
        return _daily()

    monkeypatch.setattr(service, "fetch_pending_fx_reference", fetch)
    _run(task_id)
    with SessionLocal() as db:
        expense, task = db.get(Expense, expense_id), db.get(BackgroundTask, task_id)
        assert (expense.status, expense.fx_status, expense.amount_cents) == ("pending", "pending", None)
        if interruption == "edit":
            assert expense.row_version == version + 1 and expense.original_amount_minor == 2000
            assert task.status == "completed" and json.loads(task.result_summary_json)["outcome"] == "conflict"
        else:
            assert expense.row_version == version and task.status == "cancelled"
            assert task.result_summary_json is None


@pytest.mark.parametrize("refusal_kind,code", [("viewer", "permission_denied"), ("foreign", "expense_not_found"),
    ("stale", "state_conflict"), ("revoked_device", "invalid_token")])
def test_request_requires_real_permission_ledger_and_original_version(identity, refusal_kind, code):
    expense_id, version, task_id, auth = _seed_pending_task(identity)
    with SessionLocal() as db:
        if refusal_kind == "viewer":
            member = db.scalar(select(LedgerMember).where(
                LedgerMember.ledger_id == auth.tenant_id, LedgerMember.account_id == auth.account_id))
            member.role = "viewer"
        if refusal_kind == "revoked_device":
            db.get(Device, auth.device_id).revoked_at = datetime(2026, 9, 1, tzinfo=UTC)
        db.commit()
    with SessionLocal() as db, pytest.raises(AppError) as refusal:
        service.request_pending_expense_fx(db, tenant_id="tester_1" if refusal_kind == "foreign" else auth.tenant_id,
            initiator_account_id=auth.account_id, initiator_device_id=auth.device_id,
            expense_id=expense_id, expected_row_version=version + (refusal_kind == "stale"))
    assert refusal.value.error == code
    with SessionLocal() as db:
        assert db.get(BackgroundTask, task_id).status == "queued"


def test_upload_scope_remains_refused_by_the_actual_api_writer_dependency(identity):
    _, _, _, auth = _seed_pending_task(identity)
    with pytest.raises(AppError) as refusal:
        get_current_writer_context(auth=replace(auth, scope="upload"))
    assert refusal.value.status_code == 403


def test_optional_admission_capacity_does_not_rollback_staged_bill(identity, monkeypatch):
    expense_id, _, task_id, auth = _seed_pending_task(identity)
    monkeypatch.setattr(service.background_task_service, "prepare_enqueue", Mock(side_effect=BackgroundTaskCapacityFullError))
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = db.get(Expense, expense_id)
        expense.original_amount_minor = 1200
        bump_row_version(expense)
        assert service.prepare_pending_expense_fx(db, expense=expense,
            initiator_account_id=auth.account_id, initiator_device_id=auth.device_id) is None
        db.commit()
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).original_amount_minor == 1200
        assert db.get(BackgroundTask, task_id).status == "queued"


@pytest.mark.parametrize("finish_stale_task", [False, True])
def test_edit_with_auto_sync_off_excludes_old_task_and_manual_request_uses_new_input(
    client, identity, monkeypatch, finish_stale_task,
):
    expense_id, version, task_id, _ = _seed_pending_task(identity)
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(fx_rate_auto_sync_enabled=False))
    edited = client.patch(f"/api/expenses/{expense_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": version, "original_amount_minor": 2000,
            "spent_at": "2026-05-30T04:00:00Z"})
    assert edited.status_code == 200, edited.text
    current_version = edited.json()["row_version"]
    assert current_version == version + 1
    assert edited.json()["fx_task"] is None
    if finish_stale_task:
        _run(task_id)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert service.current_pending_expense_fx_tasks(db, tenant_id="owner", expenses=[expense]) == {}
        assert service.latest_pending_expense_fx_tasks(db, tenant_id="owner", expense_ids=[expense_id])[expense_id].id == task_id
    requested = client.post(f"/api/expenses/{expense_id}/fx", headers=identity.app_headers,
        json={"expected_row_version": current_version})
    assert requested.status_code == 200, requested.text
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == requested.json()["public_id"]))
        assert task.id != task_id and task.status == "queued"
        original = json.loads(task.input_payload_json)
        assert (original["expected_row_version"], original["original_amount_minor"], original["rate_date"]) == (
            current_version, 2000, "2026-05-30")

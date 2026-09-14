"""Accepted CSV bills resume after a full FX queue without retrying terminal intents."""

import json
import threading
from dataclasses import replace
from datetime import date, time
from decimal import Decimal
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text

from app.config import get_settings
from app.database import SessionLocal
from app.models import BackgroundTask
from app.services import (
    background_task_admission,
    background_task_recovery_service,
    background_task_service,
    background_task_worker,
    fx_rate_scheduler,
    pending_fx_task_service,
)
from app.services.fx_rate_provider import EcbDailyRates, FxFetchError

pytestmark = pytest.mark.real_db
SPENT_AT = "2026-05-31T04:00:00Z"


class _TwoTicks(threading.Event):
    def __init__(self):
        super().__init__()
        self.delays = []

    def wait(self, timeout=None):
        self.delays.append(timeout)
        return len(self.delays) > 2


@pytest.fixture
def one_slot(monkeypatch):
    settings = replace(get_settings(), fx_rate_auto_sync_enabled=True,
        background_task_max_active=1, background_task_orphan_grace_seconds=0)
    for module in (background_task_admission, pending_fx_task_service, background_task_recovery_service, fx_rate_scheduler):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    submitted = Mock()
    monkeypatch.setattr("app.services.background_task_executor.submit_task", submitted)
    monkeypatch.setattr(fx_rate_scheduler, "refresh_ecb_fx_rates", Mock(return_value=[]))
    monkeypatch.setattr(fx_rate_scheduler, "_seconds_until_next_run", lambda *_: 3600)
    monkeypatch.setattr(pending_fx_task_service, "fetch_pending_fx_reference", lambda _: EcbDailyRates(
        date(2026, 5, 29), {"EUR": Decimal(1), "USD": Decimal(1), "CNY": Decimal(7)}))
    return submitted


def _apply_bills(client, identity, amounts=(1000, 2000), *, headers=None):
    request_headers = identity.app_headers if headers is None else headers
    content = "home_currency_code,amount_cents,original_currency_code,original_amount_minor,expense_time,merchant,category\n"
    content += "".join(f"CNY,,USD,{amount},{SPENT_AT},Foreign bill {amount},交通\n" for amount in amounts)
    created = client.post("/api/imports/csv", headers=request_headers,
        files={"csv_file": ("capacity.csv", content.encode(), "text/csv")})
    assert created.status_code == 201, created.text
    assert (created.json()["valid_rows"], created.json()["error_rows"]) == (len(amounts), 0)
    endpoint = f"/api/imports/csv/{created.json()['public_id']}"
    applied = client.post(f"{endpoint}/apply", headers=request_headers, json={"batch_size": len(amounts)})
    assert applied.status_code == 200, applied.text
    assert applied.json()["inserted_count"] == len(amounts)
    rows = client.get(f"{endpoint}/rows", headers=request_headers)
    assert rows.status_code == 200, rows.text
    assert len(rows.json()["items"]) == len(amounts)
    assert all(row["status"] == "applied" for row in rows.json()["items"])
    return sorted(row["expense_id"] for row in rows.json()["items"])


def _bill(client, identity, expense_id):
    response = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    return response.json()


def _tick():
    stop = _TwoTicks()
    fx_rate_scheduler._scheduler_loop(stop, [time(9, 10)], ZoneInfo("UTC"))
    return stop.delays


def _active_count():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(BackgroundTask).where(
            BackgroundTask.status.in_(("queued", "running"))))


def test_applied_csv_waits_for_capacity_then_scheduler_finishes_both_pending_conversions(client, identity, one_slot):
    expense_ids = _apply_bills(client, identity)
    original = [_bill(client, identity, expense_id) for expense_id in expense_ids]
    assert one_slot.call_count == 1 and _active_count() == 1
    assert original[0]["fx_task"]["status"] == "queued" and original[1]["fx_task"] is None
    assert all(bill["fx_status"] == "pending" and bill["amount_cents"] is None for bill in original)
    background_task_worker.run_task(one_slot.call_args.args[0], {})
    assert _active_count() == 0

    delays = _tick()

    assert one_slot.call_count == 2, "The existing scheduler must admit the accepted bill left outside a full queue"
    assert _active_count() == 1
    second_id = one_slot.call_args.args[0]
    with SessionLocal() as db:
        task = db.get(BackgroundTask, second_id)
        assert (task.tenant_id, task.source_expense_id, task.status) == ("owner", expense_ids[1], "queued")
        assert (task.initiated_by_account_id, task.initiated_by_device_id) == (None, None)
        saved = json.loads(task.input_payload_json)
        assert saved["expected_row_version"] == original[1]["row_version"]
        assert saved["rate_date"] == "2026-05-31"
        assert (saved["tenant_id"], saved["expense_id"], saved["original_currency_code"],
                saved["original_amount_minor"], saved["home_currency_code"]) == (
            "owner", expense_ids[1], "USD", original[1]["original_amount_minor"], "CNY")
    task_url = f"/api/expenses/{expense_ids[1]}/fx"
    readable = client.get(task_url, headers=identity.app_headers)
    assert readable.status_code == 200, readable.text
    assert (readable.json()["source_expense_id"], readable.json()["status"]) == (expense_ids[1], "queued")
    assert client.get(task_url, headers=identity.gray_app_headers).status_code == 404
    fx_rate_scheduler.refresh_ecb_fx_rates.assert_not_called()
    background_task_worker.run_task(second_id, {})
    for before in original:
        after = _bill(client, identity, before["id"])
        assert (after["status"], after["fx_status"], after["confirmed_at"]) == ("pending", "ready", None)
        assert (after["original_currency_code"], after["original_amount_minor"], after["expense_time"]) == (
            "USD", before["original_amount_minor"], SPENT_AT)
        assert after["amount_cents"] == before["original_amount_minor"] * 7
        assert after["fx_rate_date"] == "2026-05-29" and after["row_version"] == before["row_version"] + 1
        assert after["fx_task"]["status"] == "completed"
    _tick()
    assert one_slot.call_count == 2 and _active_count() == 0
    assert delays and all(0 < delay <= 30 for delay in delays)


def test_capacity_released_by_owner_continues_the_other_ledgers_original_bill(client, identity, one_slot):
    owner_id = _apply_bills(client, identity, (1000,))[0]
    owner_task_id = one_slot.call_args.args[0]
    other_id = _apply_bills(client, identity, (2000,), headers=identity.gray_app_headers)[0]
    other_url = f"/api/expenses/{other_id}"
    before = client.get(other_url, headers=identity.gray_app_headers)
    assert before.status_code == 200, before.text
    original = before.json()
    assert (original["status"], original["fx_status"], original["fx_task"]) == ("pending", "pending", None)
    assert one_slot.call_count == 1 and _active_count() == 1
    background_task_worker.run_task(owner_task_id, {})
    assert _active_count() == 0
    owner = _bill(client, identity, owner_id)

    _tick()

    assert one_slot.call_count == 2 and _active_count() == 1
    with SessionLocal() as db:
        task = db.get(BackgroundTask, one_slot.call_args.args[0])
        assert (task.tenant_id, task.source_expense_id, task.status) == ("tester_1", other_id, "queued")
        assert (task.initiated_by_account_id, task.initiated_by_device_id) == (None, None)
        saved = json.loads(task.input_payload_json)
        assert (saved["tenant_id"], saved["expense_id"], saved["expected_row_version"], saved["rate_date"],
                saved["original_currency_code"], saved["original_amount_minor"], saved["home_currency_code"]) == (
            "tester_1", other_id, original["row_version"], "2026-05-31", "USD", 2000, "CNY")
    task_url = f"{other_url}/fx"
    readable = client.get(task_url, headers=identity.gray_app_headers)
    assert readable.status_code == 200, readable.text
    assert (readable.json()["source_expense_id"], readable.json()["status"]) == (other_id, "queued")
    assert client.get(task_url, headers=identity.app_headers).status_code == 404
    assert client.get(other_url, headers=identity.app_headers).status_code == 404
    assert _bill(client, identity, owner_id) == owner


@pytest.mark.parametrize("terminal", ["failed", "cancelled", "orphaned_after_restart"])
def test_scheduler_continues_unadmitted_bill_without_automatically_retrying_original_task(
    client, identity, one_slot, monkeypatch, terminal,
):
    expense_ids = _apply_bills(client, identity)
    first = _bill(client, identity, expense_ids[0])
    task_id = one_slot.call_args.args[0]
    if terminal == "failed":
        monkeypatch.setattr(pending_fx_task_service, "fetch_pending_fx_reference", Mock(side_effect=FxFetchError("unavailable")))
        background_task_worker.run_task(task_id, {})
    elif terminal == "cancelled":
        with SessionLocal() as db:
            background_task_service.request_cancellation(db, first["fx_task"]["public_id"], account_id=None, tenant_id="owner")
        background_task_worker.run_task(task_id, {})
    else:
        assert background_task_service.recover_orphaned_tasks() == 1
    original_task = _bill(client, identity, expense_ids[0])["fx_task"]
    assert original_task["status"] == ("cancelled" if terminal == "cancelled" else "failed")
    assert _active_count() == 0

    _tick()

    assert one_slot.call_count == 2, "Only the bill without any admitted task should receive the free slot"
    second = _bill(client, identity, expense_ids[1])
    assert second["fx_task"]["status"] == "queued" and _active_count() == 1
    unchanged = _bill(client, identity, expense_ids[0])
    assert unchanged["fx_task"] == original_task
    assert (unchanged["row_version"], unchanged["status"], unchanged["amount_cents"]) == (first["row_version"], "pending", None)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(BackgroundTask).where(
            BackgroundTask.source_expense_id == expense_ids[0])) == 1


def test_terminal_tasks_at_the_front_cannot_starve_a_later_bill_without_a_task(client, identity, one_slot, monkeypatch):
    expense_ids = _apply_bills(client, identity, tuple(range(1000, 34000, 1000)))
    monkeypatch.setattr(pending_fx_task_service, "fetch_pending_fx_reference", Mock(side_effect=FxFetchError("unavailable")))
    for index, expense_id in enumerate(expense_ids[:32]):
        if index:
            bill = _bill(client, identity, expense_id)
            response = client.post(f"/api/expenses/{expense_id}/fx", headers=identity.app_headers,
                json={"expected_row_version": bill["row_version"]})
            assert response.status_code == 200, response.text
        background_task_worker.run_task(one_slot.call_args.args[0], {})
        assert _bill(client, identity, expense_id)["fx_task"]["status"] == "failed"
    assert one_slot.call_count == 32 and _active_count() == 0
    assert _bill(client, identity, expense_ids[32])["fx_task"] is None

    _tick()

    assert one_slot.call_count == 33, "Two scheduler ticks must look beyond existing failed tasks"
    assert _active_count() == 1
    last = _bill(client, identity, expense_ids[32])
    assert (last["fx_task"]["status"], last["fx_task"]["source_expense_id"]) == ("queued", expense_ids[32])
    with SessionLocal() as db:
        tasks = list(db.scalars(select(BackgroundTask).where(BackgroundTask.source_expense_id.in_(expense_ids[:32]))))
        assert len(tasks) == 32 and all(task.status == "failed" for task in tasks)


def test_full_capacity_keeps_the_blocked_bill_before_later_bills_in_the_same_loop(client, identity, one_slot):
    expense_ids = _apply_bills(client, identity, (1000, 2000, 3000))
    first_task_id = one_slot.call_args.args[0]
    blocked = _bill(client, identity, expense_ids[1])
    stop = _TwoTicks()
    wait = stop.wait

    def release_first_after_a_full_tick(timeout=None):
        if len(stop.delays) == 1:
            assert one_slot.call_count == 1 and _active_count() == 1
            assert _bill(client, identity, expense_ids[1])["fx_task"] is None
            assert _bill(client, identity, expense_ids[2])["fx_task"] is None
            background_task_worker.run_task(first_task_id, {})
            assert _active_count() == 0
        return wait(timeout)

    stop.wait = release_first_after_a_full_tick
    fx_rate_scheduler._scheduler_loop(stop, [time(9, 10)], ZoneInfo("UTC"))

    assert one_slot.call_count == 2, "The next free slot belongs to the original capacity-blocked bill"
    with SessionLocal() as db:
        resumed = db.get(BackgroundTask, one_slot.call_args.args[0])
        assert (resumed.source_expense_id, resumed.status) == (expense_ids[1], "queued")
        saved = json.loads(resumed.input_payload_json)
        assert (saved["expected_row_version"], saved["original_amount_minor"], saved["rate_date"]) == (
            blocked["row_version"], blocked["original_amount_minor"], "2026-05-31")
    assert _bill(client, identity, expense_ids[2])["fx_task"] is None
    assert _active_count() == 1


def test_next_candidate_sees_previous_task_committed_and_admission_lock_released(client, identity, one_slot, monkeypatch):
    expense_ids = _apply_bills(client, identity, (1000, 2000, 3000))
    background_task_worker.run_task(one_slot.call_args.args[0], {})
    settings = replace(background_task_admission.get_settings(), background_task_max_active=2)
    monkeypatch.setattr(background_task_admission, "get_settings", lambda: settings)
    resolve = pending_fx_task_service.resolve_expense
    observations = []

    def observe_before_next_expense(db, tenant_id, ref, **kwargs):
        if ref == expense_ids[2] and kwargs.get("for_update"):
            with SessionLocal() as observer:
                previous = observer.scalar(select(BackgroundTask).where(
                    BackgroundTask.source_expense_id == expense_ids[1], BackgroundTask.task_type == "expense_fx"))
                assert previous is not None, "The previous candidate must commit before the next Expense lock"
                assert previous.status == "queued"
                acquired = observer.scalar(text(
                    "SELECT pg_try_advisory_xact_lock(hashtext(current_database()), hashtext(:label))"
                ), {"label": "ticketbox-background-task-admission"})
                assert acquired is True, "A prior admission lock must not cross into the next candidate transaction"
                observations.append(previous.id)
        return resolve(db, tenant_id, ref, **kwargs)

    monkeypatch.setattr(pending_fx_task_service, "resolve_expense", observe_before_next_expense)

    _tick()

    assert observations, "The actual scheduler must reach the second eligible bill"
    assert one_slot.call_count == 3 and _active_count() == 2
    for expense_id in expense_ids[1:]:
        bill = _bill(client, identity, expense_id)
        assert (bill["status"], bill["fx_task"]["status"], bill["fx_task"]["source_expense_id"]) == (
            "pending", "queued", expense_id)

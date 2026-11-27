from __future__ import annotations

import threading
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import (
    Account,
    ApiIdempotencyKey,
    Expense,
    Ledger,
    LedgerMember,
    RecurringItem,
    RecurringOccurrence,
)
from app.services.background_task_admission import (
    BackgroundTaskCapacityFullError,
    _reserve_active_slot,
)
from app.services.background_task_recovery_service import _recovery_loop
from app.services.idempotency import (
    IDEMPOTENCY_STATUS_IN_PROGRESS,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
)
from app.services.ledger_archive_service import _authorize_ledger_owner
from app.services.recurring_occurrence_query import fulfilled_periods, occurrence_response
from app.services.time_service import now_utc
from tests.bill_split_test_support import _bearer_for_account_ledger, _seed_receiver


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner_id = db.scalar(select(Ledger.owner_account_id).where(Ledger.ledger_id == "owner"))
        assert owner_id is not None
        return int(owner_id)


def test_subtask_idempotency_isolates_different_actors_in_same_ledger(
    client: TestClient,
    identity,
) -> None:
    peer_account_id = _seed_receiver()
    with SessionLocal() as db:
        db.add(LedgerMember(ledger_id="owner", account_id=peer_account_id, role="member"))
        db.commit()
    peer_headers = _bearer_for_account_ledger(peer_account_id, "owner")

    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=1000,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=1000,
            merchant="咖啡",
            category="餐饮",
            status="pending",
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id
        row_version = expense.row_version

    key = str(uuid4())
    body = {
        "expected_row_version": row_version,
        "items": [{"name": "拿铁", "amount_cents": 1000, "category": "餐饮"}],
    }
    first = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json=body,
    )
    assert first.status_code == 200, first.text

    other_actor_replay = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**peer_headers, "Idempotency-Key": key},
        json=body,
    )
    assert other_actor_replay.status_code == 422, other_actor_replay.text
    assert other_actor_replay.json()["error"] == "idempotency_key_reused"

    owner_second_device_headers = _bearer_for_account_ledger(_owner_account_id(), "owner")
    other_device_replay = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**owner_second_device_headers, "Idempotency-Key": key},
        json=body,
    )
    assert other_device_replay.status_code == 422, other_device_replay.text
    assert other_device_replay.json()["error"] == "idempotency_key_reused"

    legacy_key = str(uuid4())
    legacy_fp = fingerprint_request(
        operation="replace_items",
        target_id=str(expense_id),
        body={"items": [{"name": "拿铁", "amount_cents": 1000, "category": "餐饮"}]},
        expected_row_version=row_version,
    )
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=legacy_key,
                operation="replace_items",
                target_type="expense",
                target_id=str(expense_id),
                request_fingerprint=legacy_fp,
                status="succeeded",
                resource_type="expense",
                resource_id=str(expense_id),
                created_at=now_utc(),
                completed_at=now_utc(),
                expires_at=now_utc() + timedelta(days=30),
            )
        )
        db.commit()

    legacy_retry = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": legacy_key},
        json=body,
    )
    assert legacy_retry.status_code == 409, legacy_retry.text
    assert legacy_retry.json()["error"] == "expense_subtask_original_requires_review"

    legacy_inflight_key = str(uuid4())
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=legacy_inflight_key,
                operation="replace_items",
                target_type="expense",
                target_id=str(expense_id),
                request_fingerprint=legacy_fp,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=30),
            )
        )
        db.commit()

    legacy_inflight_retry = client.put(
        f"/api/expenses/{expense_id}/items",
        headers={**identity.app_headers, "Idempotency-Key": legacy_inflight_key},
        json=body,
    )
    assert legacy_inflight_retry.status_code == 409, legacy_inflight_retry.text
    assert legacy_inflight_retry.json()["error"] == "expense_subtask_original_requires_review"


@pytest.mark.real_db
def test_stale_idempotency_reclaim_uses_atomic_cas(identity, monkeypatch) -> None:
    from app.services import idempotency as idempotency_mod

    key = str(uuid4())
    fp = fingerprint_request(
        operation="cas_probe",
        target_id="1",
        body={"v": 1},
        expected_row_version=1,
    )
    stale_time = now_utc() - timedelta(minutes=20)
    with SessionLocal() as db:
        row = ApiIdempotencyKey(
            tenant_id="owner",
            idempotency_key=key,
            operation="cas_probe",
            target_type="expense",
            target_id="1",
            request_fingerprint=fp,
            status=IDEMPOTENCY_STATUS_IN_PROGRESS,
            created_at=stale_time,
            expires_at=stale_time + timedelta(days=30),
        )
        db.add(row)
        db.commit()

    barrier = threading.Barrier(2)
    real_ensure_utc = idempotency_mod.ensure_utc

    def _synchronized_ensure_utc(value):
        result = real_ensure_utc(value)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(idempotency_mod, "ensure_utc", _synchronized_ensure_utc)

    results: list[IdempotencyOutcomeKind] = []
    lock = threading.Lock()

    def _worker() -> None:
        with SessionLocal() as db:
            outcome = claim_idempotency_key(
                db,
                tenant_id="owner",
                idempotency_key=key,
                operation="cas_probe",
                request_fingerprint=fp,
                target_type="expense",
                target_id="1",
            )
            db.commit()
            with lock:
                results.append(outcome.kind)

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert sorted(r.value for r in results) == [
        IdempotencyOutcomeKind.IN_PROGRESS.value,
        IdempotencyOutcomeKind.PROCEED.value,
    ]


def test_ocr_recovery_loop_survives_single_file_permission_error(identity) -> None:
    from types import SimpleNamespace

    from app.config import get_settings
    from app.models import BackgroundTask
    from app.services.background_task_admission import _probe_pending_image_sizes

    with SessionLocal() as db:
        owner_exp = Expense(
            tenant_id="owner",
            merchant="权限测试",
            category="其他",
            status="pending",
            image_path="uploads/owner/2026/09/perm.jpg",
        )
        other_small = Expense(
            tenant_id="tester_1",
            merchant="健康账本小图",
            category="其他",
            status="pending",
            image_path="uploads/tester_1/2026/09/ok.jpg",
        )
        other_large = Expense(
            tenant_id="tester_1",
            merchant="健康账本超额图",
            category="其他",
            status="pending",
            image_path="uploads/tester_1/2026/09/large.jpg",
        )
        db.add_all([owner_exp, other_small, other_large])
        db.flush()
        db.add(
            BackgroundTask(
                public_id=str(uuid4()),
                tenant_id="owner",
                task_type="expense_enrichment",
                status="queued",
                source_expense_id=owner_exp.id,
            )
        )
        db.commit()
        owner_exp_id = owner_exp.id
        other_small_id = other_small.id
        other_large_id = other_large.id

    bad_path = Path("C:/nonexistent/perm.jpg")
    ok_path = Path("C:/nonexistent/ok.jpg")
    large_path = Path("C:/nonexistent/large.jpg")
    base_settings = get_settings()
    custom_settings = SimpleNamespace(
        background_task_max_active=base_settings.background_task_max_active,
        background_task_max_ledger_active=base_settings.background_task_max_ledger_active,
        background_task_max_image_bytes=48 * 1024 * 1024,
        background_task_max_ledger_image_bytes=32 * 1024 * 1024,
    )
    remaining_global = 16 * 1024 * 1024

    def _resolve(rel_path: str | None, *, tenant_id: str) -> Path:
        if tenant_id == "owner":
            return bad_path
        if rel_path and rel_path.endswith("large.jpg"):
            return large_path
        return ok_path

    def _fake_stat(self: Path):
        if self == bad_path:
            raise PermissionError("access denied")
        if self == large_path:
            return SimpleNamespace(st_size=remaining_global + 1)
        return SimpleNamespace(st_size=remaining_global)

    with (
        SessionLocal() as db,
        patch(
            "app.services.background_task_admission.get_settings",
            return_value=custom_settings,
        ),
        patch(
            "app.services.background_task_admission.resolve_upload_path_for_tenant",
            side_effect=_resolve,
        ),
        patch.object(Path, "stat", _fake_stat),
    ):
        sizes, unreadable = _probe_pending_image_sizes(
            db, {("owner", owner_exp_id), ("tester_1", other_small_id)}
        )
        assert unreadable == {"owner"}
        assert sizes == {("tester_1", other_small_id): remaining_global}
        with pytest.raises(BackgroundTaskCapacityFullError):
            _reserve_active_slot(db, ledger_id="owner", source_expense_id=owner_exp_id)
        _reserve_active_slot(db, ledger_id="tester_1", source_expense_id=other_small_id)
        with pytest.raises(BackgroundTaskCapacityFullError):
            _reserve_active_slot(db, ledger_id="tester_1", source_expense_id=other_large_id)

    stop_event = threading.Event()
    calls = {"n": 0}

    def _boom_then_stop() -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("single file unreadable")
        stop_event.set()
        return 0

    with (
        patch("app.services.background_task_recovery_service.resume_due_ocr_tasks", side_effect=_boom_then_stop),
        patch.object(stop_event, "wait", return_value=False),
    ):
        _recovery_loop(stop_event)
    assert calls["n"] == 2


def test_recurring_occurrence_response_never_contradicts_empty_row(identity) -> None:
    with SessionLocal() as db:
        item = RecurringItem(
            tenant_id="owner",
            merchant_key="rent",
            merchant_name="房租",
            baseline_amount_cents=300000,
            last_amount_cents=300000,
            home_currency_code="CNY",
            frequency="monthly",
            next_expected_date=date(2026, 9, 10),
            status="active",
        )
        db.add(item)
        db.flush()
        with patch(
            "app.services.recurring_occurrence_query.fulfilled_periods",
            return_value={item.id: {date(2026, 9, 1)}},
        ):
            resp = occurrence_response(db, item=item, period=date(2026, 9, 1))
        assert resp.state == "unfulfilled"
        assert resp.expense_id is None
        assert resp.paid_amount_cents is None
        assert resp.reserved_amount_cents == 300000

        null_amount_expense = Expense(
            tenant_id="owner",
            amount_cents=None,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=None,
            merchant="房租",
            category="居住",
            status="confirmed",
            accounting_date=date(2026, 9, 10),
            calendar_revision=1,
            confirmed_at=now_utc(),
        )
        db.add(null_amount_expense)
        db.flush()
        db.add(
            RecurringOccurrence(
                tenant_id="owner",
                series_id=item.id,
                period_start=date(2026, 9, 1),
                expense_id=null_amount_expense.id,
            )
        )
        db.flush()
        paid_map = fulfilled_periods(db, tenant_id="owner", series_ids=[item.id])
        null_resp = occurrence_response(db, item=item, period=date(2026, 9, 1))
        db.rollback()
    assert date(2026, 9, 1) not in paid_map.get(item.id, set())
    assert null_resp.state == "needs_review"
    assert null_resp.payment_review_reason == "unavailable"
    assert null_resp.reserved_amount_cents == 300000


def test_ledger_archive_authorization_requires_matching_owner_column(identity) -> None:
    owner_account_id = _owner_account_id()
    with SessionLocal() as db:
        other = Account(display_name="Other Owner")
        db.add(other)
        db.flush()
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        assert ledger is not None
        ledger.owner_account_id = other.id
        db.flush()
        try:
            _authorize_ledger_owner(db, ledger_id="owner", actor_account_id=owner_account_id)
            raise AssertionError("expected ledger_forbidden on owner mismatch")
        except AppError as exc:
            assert exc.error == "ledger_forbidden"
            assert exc.status_code == 403
        finally:
            db.rollback()

    with SessionLocal() as db:
        second_owner = Account(display_name="Second Active Owner")
        db.add(second_owner)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=second_owner.id, role="owner"))
        db.flush()
        try:
            _authorize_ledger_owner(db, ledger_id="owner", actor_account_id=owner_account_id)
            raise AssertionError("expected ledger_forbidden on dual active owners")
        except AppError as exc:
            assert exc.error == "ledger_forbidden"
            assert exc.status_code == 403
        finally:
            db.rollback()

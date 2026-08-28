from __future__ import annotations

import pytest
from sqlalchemy import select

import app.services.expense_service._create as create_service
from app.database import SessionLocal
from app.models import BackgroundTask, Expense
from app.services.background_task_service import TaskCancelledError
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_service import create_pending_expense
from app.services.file_service import save_upload_bytes
from app.services.ledger_service import find_owner_account_id_for_ledger
from app.services.ocr_service import OcrExtraction, OcrResult
from app.services.optimistic_concurrency import bump_row_version
from app.services.pending_enrichment_task_service import (
    PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
    run_pending_expense_enrichment_task,
)
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES


def _seed_pending_enrichment_task() -> tuple[int, int, int]:
    saved = save_upload_bytes(
        PNG_BYTES,
        tenant_id="owner",
        filename="receipt.png",
        content_type="image/png",
    )
    with SessionLocal() as db:
        expense = create_pending_expense(
            db,
            saved,
            "owner",
            source="网页上传",
            run_enrichment=False,
        )
        account_id = find_owner_account_id_for_ledger(db, ledger_id="owner")
        assert account_id is not None
        task = BackgroundTask(
            task_type=PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
            tenant_id="owner",
            initiated_by_account_id=account_id,
            status="running",
            progress_total=1,
            started_at=now_utc(),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return expense.id, expense.row_version, task.id


def _ocr_result() -> list[OcrExtraction]:
    return [
        OcrExtraction(
            provider_name="mock",
            ocr_model="test-model",
            result=OcrResult(
                raw_text="盒马\n交易金额：19.90",
                confidence=0.98,
                amount_cents=1990,
                merchant="盒马",
            ),
        )
    ]


@pytest.mark.real_db
def test_enrichment_predecessor_rejects_a_newer_manual_edit(
    monkeypatch,
    *,
    identity,
) -> None:
    expense_id, predecessor_row_version, task_id = _seed_pending_enrichment_task()

    def edit_while_ocr_is_running(*_args, **_kwargs):
        with SessionLocal() as user_db:
            resolve_write_capability(user_db)
            expense = user_db.scalar(
                select(Expense).where(
                    Expense.id == expense_id,
                    Expense.tenant_id == "owner",
                )
            )
            assert expense is not None
            assert expense.row_version == predecessor_row_version
            expense.amount_cents = 8_888
            expense.merchant = "用户后来修改"
            expense.updated_at = now_utc()
            bump_row_version(expense)
            user_db.commit()
        return _ocr_result()

    monkeypatch.setattr(
        create_service,
        "collect_auto_ocr_extractions",
        edit_while_ocr_is_running,
    )
    monkeypatch.setattr(create_service, "_try_generate_thumbnail", lambda *_args: None)

    with SessionLocal() as task_db:
        task = task_db.get(BackgroundTask, task_id)
        assert task is not None
        run_pending_expense_enrichment_task(
            task_db,
            task,
            {
                "expense_id": expense_id,
                "tenant_id": "owner",
                "timezone_name": None,
                "expected_row_version": predecessor_row_version,
            },
        )
        assert task.result_summary_json is not None
        assert '"outcome":"conflict"' in task.result_summary_json
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.status == "pending"
        assert expense.amount_cents == 8_888
        assert expense.merchant == "用户后来修改"
        assert expense.row_version == predecessor_row_version + 1


@pytest.mark.real_db
def test_enrichment_observes_cancellation_after_ocr_before_mutation(
    monkeypatch,
    *,
    identity,
) -> None:
    expense_id, predecessor_row_version, task_id = _seed_pending_enrichment_task()

    def cancel_while_ocr_is_running(*_args, **_kwargs):
        with SessionLocal() as cancel_db:
            task = cancel_db.get(BackgroundTask, task_id)
            assert task is not None
            task.cancellation_requested_at = now_utc()
            cancel_db.commit()
        return _ocr_result()

    monkeypatch.setattr(
        create_service,
        "collect_auto_ocr_extractions",
        cancel_while_ocr_is_running,
    )
    monkeypatch.setattr(create_service, "_try_generate_thumbnail", lambda *_args: None)

    with SessionLocal() as task_db:
        task = task_db.get(BackgroundTask, task_id)
        assert task is not None
        with pytest.raises(TaskCancelledError):
            run_pending_expense_enrichment_task(
                task_db,
                task,
                {
                    "expense_id": expense_id,
                    "tenant_id": "owner",
                    "timezone_name": None,
                    "expected_row_version": predecessor_row_version,
                },
            )

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.status == "pending"
        assert expense.amount_cents is None
        assert expense.merchant is None
        assert expense.row_version == predecessor_row_version


@pytest.mark.real_db
def test_thumbnail_io_finishes_before_expense_apply_lock(
    monkeypatch,
    *,
    identity,
) -> None:
    expense_id, predecessor_row_version, _task_id = _seed_pending_enrichment_task()
    real_resolve_expense = create_service.resolve_expense
    apply_lock_started = False

    def observe_resolve(*args, **kwargs):
        nonlocal apply_lock_started
        if kwargs.get("for_update"):
            apply_lock_started = True
        return real_resolve_expense(*args, **kwargs)

    def generate_thumbnail_before_lock(*_args, **_kwargs):
        assert apply_lock_started is False
        return None

    monkeypatch.setattr(create_service, "resolve_expense", observe_resolve)
    monkeypatch.setattr(
        create_service,
        "collect_auto_ocr_extractions",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        create_service,
        "_try_generate_thumbnail",
        generate_thumbnail_before_lock,
    )

    result = create_service.enrich_pending_expense(
        expense_id,
        "owner",
        expected_row_version=predecessor_row_version,
    )

    assert result.outcome == "no_result"
    assert apply_lock_started is True


@pytest.mark.real_db
def test_enrichment_observes_cancellation_during_thumbnail_before_mutation(
    monkeypatch,
    *,
    identity,
) -> None:
    expense_id, predecessor_row_version, task_id = _seed_pending_enrichment_task()

    monkeypatch.setattr(
        create_service,
        "collect_auto_ocr_extractions",
        lambda *_args, **_kwargs: _ocr_result(),
    )

    def cancel_during_thumbnail(*_args, **_kwargs):
        with SessionLocal() as cancel_db:
            task = cancel_db.get(BackgroundTask, task_id)
            assert task is not None
            task.cancellation_requested_at = now_utc()
            cancel_db.commit()
        return None

    monkeypatch.setattr(
        create_service,
        "_try_generate_thumbnail",
        cancel_during_thumbnail,
    )

    with SessionLocal() as task_db:
        task = task_db.get(BackgroundTask, task_id)
        assert task is not None
        with pytest.raises(TaskCancelledError):
            run_pending_expense_enrichment_task(
                task_db,
                task,
                {
                    "expense_id": expense_id,
                    "tenant_id": "owner",
                    "timezone_name": None,
                    "expected_row_version": predecessor_row_version,
                },
            )

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        assert expense.amount_cents is None
        assert expense.merchant is None
        assert expense.row_version == predecessor_row_version

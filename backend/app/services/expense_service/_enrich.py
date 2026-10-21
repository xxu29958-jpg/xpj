"""Background OCR/thumbnail enrichment for one committed Pending expense."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError, PathTraversalError
from app.models import Expense
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.classify_service import classify_expense
from app.services.currency_binding_service import resolve_write_capability
from app.services.duplicate_service import mark_duplicate_status
from app.services.expense_query import resolve_expense
from app.services.expense_service._enrichment_receipt import (
    lock_enrichment_receipt,
    require_enrichment_actor,
    stage_enrichment_receipt,
)
from app.services.expense_service._helpers import (
    _replace_ocr_draft_items_from_text,
)
from app.services.expense_service._ocr_facts import apply_ocr_result_and_append_fact
from app.services.expense_service._thumbnail_publication import (
    claim_staged_thumbnail,
    publish_claimed_thumbnail,
)
from app.services.ocr_retry_receipt import stage_legacy_retry_receipt
from app.services.ocr_service import OcrExtraction, collect_auto_ocr_extractions
from app.services.optimistic_concurrency import bump_row_version
from app.services.original_read_service import read_original_snapshot
from app.services.thumb_service import (
    StagedThumbnail,
    discard_staged_thumbnail,
    stage_thumbnail,
)
from app.services.time_service import now_utc

logger = logging.getLogger(__name__)

_AUTO_ENRICHMENT_FAILURES = (
    AppError,
    ImportError,
    SQLAlchemyError,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
)
_ENRICHMENT_NON_OCC_COLUMNS = frozenset({"thumbnail_path", "updated_at", "row_version"})


@dataclass(frozen=True, slots=True)
class PendingEnrichmentResult:
    expense_id: int
    outcome: Literal["updated", "no_result", "not_pending", "conflict", "failed"]
    row_version: int | None


@dataclass(frozen=True, slots=True)
class _PreparedEnrichment:
    predecessor_row_version: int
    thumbnail_source_path: str | None
    thumbnail_source_hash: str | None
    thumbnail_needed: bool
    ocr_extractions: tuple[OcrExtraction, ...]


def _enrichment_occ_snapshot(expense: Expense) -> tuple[tuple[str, object], ...]:
    """Snapshot user-visible facts while excluding the derived thumbnail cache."""
    return tuple(
        (column.key, getattr(expense, column.key))
        for column in Expense.__table__.columns
        if column.key not in _ENRICHMENT_NON_OCC_COLUMNS
    )


def _checkpoint(callback: Callable[[], None] | None) -> None:
    if callback is not None:
        callback()


def _try_stage_thumbnail(relative_path: str | None, tenant_id: str, expected_sha256: str | None) -> StagedThumbnail | None:
    try:
        return stage_thumbnail(relative_path, tenant_id=tenant_id, expected_sha256=expected_sha256)
    except (AppError, OSError, PathTraversalError, RecursionError, RuntimeError, ValueError) as exc:
        logger.warning("event=thumbnail_staging_failed error_type=%s", type(exc).__name__)
        return None


def _publish_enrichment_thumbnail_best_effort(
    db: Session,
    expense: Expense,
    staged: StagedThumbnail,
    *,
    expense_id: int,
    tenant_id: str,
) -> None:
    try:
        publish_claimed_thumbnail(db, expense, staged)
    except (OSError, SQLAlchemyError):
        logger.exception(
            "thumbnail publication failed after durable owner commit for expense_id=%s ledger=%s",
            expense_id,
            tenant_id,
        )


def _prepare_enrichment(
    expense_id: int,
    tenant_id: str,
    timezone_name: str | None,
    expected_row_version: int | None,
    *,
    raise_on_failure: bool,
    explicit_retry: bool = False,
) -> _PreparedEnrichment | PendingEnrichmentResult:
    from app.database import SessionLocal

    with SessionLocal() as db:
        expense = resolve_expense(db, tenant_id, expense_id)
        if expense is None or expense.status != "pending":
            return PendingEnrichmentResult(
                expense_id=expense_id,
                outcome="not_pending",
                row_version=expense.row_version if expense is not None else None,
            )
        predecessor_row_version = expense.row_version if expected_row_version is None else expected_row_version
        if expense.row_version != predecessor_row_version:
            return PendingEnrichmentResult(
                expense_id=expense_id,
                outcome="conflict",
                row_version=expense.row_version,
            )
        # Copy values into a transient input, then close the read transaction
        # before snapshot IO, model startup or inference begins.
        snapshot = Expense(**{column.key: getattr(expense, column.key) for column in Expense.__table__.columns})
    if explicit_retry:
        from app.services.expense_service._ocr import extract_explicit_ocr

        extractions = [extract_explicit_ocr(snapshot, timezone_name)]
    else:
        extractions = collect_auto_ocr_extractions(snapshot, timezone_name=timezone_name, raise_on_failure=raise_on_failure)
    return _PreparedEnrichment(
        predecessor_row_version=predecessor_row_version,
        thumbnail_source_path=snapshot.image_path,
        thumbnail_source_hash=snapshot.image_hash,
        thumbnail_needed=not snapshot.thumbnail_path,
        ocr_extractions=tuple(extractions),
    )


def _commit_result(db: Session, task, result: PendingEnrichmentResult) -> PendingEnrichmentResult:
    stage_enrichment_receipt(task, result)
    stage_legacy_retry_receipt(db, task, result)
    db.commit()
    return result


def _complete_without_inference(task_id: int | None, expense_id: int, tenant_id: str,
                                result: PendingEnrichmentResult) -> PendingEnrichmentResult:
    if task_id is None:
        return result
    from app.database import SessionLocal

    with SessionLocal() as db:
        require_enrichment_actor(db, task_id, tenant_id)
        task = lock_enrichment_receipt(db, task_id, expense_id)
        if task.result_summary_json is not None:
            return PendingEnrichmentResult(**json.loads(task.result_summary_json))
        return _commit_result(db, task, result)


def _verify_extraction_source(expense: Expense, prepared: _PreparedEnrichment) -> None:
    for extraction in prepared.ocr_extractions:
        evidence = extraction.result.evidence
        if evidence is not None:
            with read_original_snapshot(relative_path=expense.image_path, tenant_id=expense.tenant_id,
                                        expected_sha256=expense.image_hash) as original:
                if original.sha256 != evidence["input_sha256"]:
                    raise AppError("ocr_input_changed", status_code=409)


def _apply_extractions(db: Session, expense: Expense, prepared: _PreparedEnrichment,
                       timezone_name: str | None) -> bool:
    """Stage draft fields and immutable facts under the caller's apply locks."""
    occ_snapshot = _enrichment_occ_snapshot(expense)
    for extraction in prepared.ocr_extractions:
        apply_ocr_result_and_append_fact(db, expense=expense, result=extraction.result,
            provider_name=extraction.provider_name, ocr_model=extraction.ocr_model, timezone_name=timezone_name)
        _replace_ocr_draft_items_from_text(db, expense, extraction.result.raw_text, timezone_name=timezone_name)
    if expense.category == "其他":
        classify_expense(db, expense)
    ensure_category_preference_for_name(db, tenant_id=expense.tenant_id, name=expense.category)
    if expense.amount_cents is not None or expense.merchant or expense.expense_time is not None:
        mark_duplicate_status(db, expense)
    return _enrichment_occ_snapshot(expense) != occ_snapshot


def _apply_enrichment(
    expense_id: int,
    tenant_id: str,
    timezone_name: str | None,
    prepared: _PreparedEnrichment,
    staged_thumbnail: StagedThumbnail | None,
    before_apply: Callable[[], None] | None,
    task_id: int | None,
) -> PendingEnrichmentResult:
    from app.database import SessionLocal

    with SessionLocal() as db:
        require_enrichment_actor(db, task_id, tenant_id)
        expense = resolve_expense(db, tenant_id, expense_id, for_update=True)
        task = lock_enrichment_receipt(db, task_id, expense_id)
        if task is not None and task.result_summary_json is not None:
            return PendingEnrichmentResult(**json.loads(task.result_summary_json))
        if expense is None or expense.status != "pending":
            return _commit_result(db, task, PendingEnrichmentResult(
                expense_id=expense_id,
                outcome="not_pending",
                row_version=expense.row_version if expense is not None else None,
            ))
        expected_source = (prepared.predecessor_row_version, prepared.thumbnail_source_path, prepared.thumbnail_source_hash, None)
        if (expense.row_version, expense.image_path, expense.image_hash, expense.image_deleted_at) != expected_source:
            return _commit_result(db, task, PendingEnrichmentResult(
                expense_id=expense_id,
                outcome="conflict",
                row_version=expense.row_version,
            ))
        _checkpoint(before_apply)
        resolve_write_capability(db)
        _verify_extraction_source(expense, prepared)
        user_visible_changed = _apply_extractions(db, expense, prepared, timezone_name)
        result_row_version = prepared.predecessor_row_version
        if prepared.ocr_extractions or user_visible_changed:
            expense.updated_at = now_utc()
            bump_row_version(expense)
            result_row_version += 1
        thumbnail_to_publish: StagedThumbnail | None = None
        if staged_thumbnail is not None and claim_staged_thumbnail(
            expense,
            staged_thumbnail,
            replace_missing_reference=False,
        ):
            thumbnail_to_publish = staged_thumbnail
        result = PendingEnrichmentResult(
            expense_id=expense.id,
            outcome="updated" if user_visible_changed else "no_result",
            row_version=result_row_version,
        )
        _commit_result(db, task, result)
        if thumbnail_to_publish is not None:
            _publish_enrichment_thumbnail_best_effort(
                db,
                expense,
                thumbnail_to_publish,
                expense_id=expense_id,
                tenant_id=tenant_id,
            )
        return result


def _failed_enrichment_result(
    expense_id: int,
    tenant_id: str,
) -> PendingEnrichmentResult:
    logger.exception(
        "auto enrichment failed for expense_id=%s tenant_id=%s",
        expense_id,
        tenant_id,
    )
    return PendingEnrichmentResult(
        expense_id=expense_id,
        outcome="failed",
        row_version=None,
    )


def enrich_pending_expense(
    expense_id: int,
    tenant_id: str,
    timezone_name: str | None = None,
    *,
    expected_row_version: int | None = None,
    before_apply: Callable[[], None] | None = None,
    raise_on_failure: bool = False,
    task_id: int | None = None,
    explicit_retry: bool = False,
) -> PendingEnrichmentResult:
    """Run provider work outside the short OCC apply transaction."""
    staged_thumbnail: StagedThumbnail | None = None
    try:
        prepared = _prepare_enrichment(
            expense_id,
            tenant_id,
            timezone_name,
            expected_row_version,
            raise_on_failure=raise_on_failure,
            explicit_retry=explicit_retry,
        )
        if isinstance(prepared, PendingEnrichmentResult):
            return _complete_without_inference(task_id, expense_id, tenant_id, prepared)
        _checkpoint(before_apply)
        if prepared.thumbnail_needed:
            staged_thumbnail = _try_stage_thumbnail(
                prepared.thumbnail_source_path,
                tenant_id,
                prepared.thumbnail_source_hash,
            )
        _checkpoint(before_apply)
        return _apply_enrichment(
            expense_id,
            tenant_id,
            timezone_name,
            prepared,
            staged_thumbnail,
            before_apply,
            task_id,
        )
    except _AUTO_ENRICHMENT_FAILURES:
        if raise_on_failure:
            _failed_enrichment_result(expense_id, tenant_id)
            raise
        return _failed_enrichment_result(expense_id, tenant_id)
    finally:
        discard_staged_thumbnail(staged_thumbnail)


__all__ = ["PendingEnrichmentResult", "enrich_pending_expense"]

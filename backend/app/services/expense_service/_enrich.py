"""Background OCR/thumbnail enrichment for one committed Pending expense."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError, PathTraversalError
from app.models import Expense
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.classify_service import classify_expense
from app.services.currency_binding_service import resolve_write_capability
from app.services.duplicate_service import mark_duplicate_status
from app.services.expense_query import resolve_expense
from app.services.expense_service._helpers import (
    _record_background_failure,
    _replace_ocr_draft_items_from_text,
)
from app.services.expense_service._ocr_facts import apply_ocr_result_and_append_fact
from app.services.ocr_service import OcrExtraction, collect_auto_ocr_extractions
from app.services.optimistic_concurrency import bump_row_version
from app.services.thumb_service import (
    StagedThumbnail,
    discard_staged_thumbnail,
    publish_staged_thumbnail,
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


def _try_stage_thumbnail(relative_path: str | None, tenant_id: str) -> StagedThumbnail | None:
    try:
        return stage_thumbnail(relative_path, tenant_id=tenant_id)
    except (OSError, PathTraversalError, RecursionError, RuntimeError, ValueError):
        _record_background_failure("thumbnail")
        logger.exception(
            "thumbnail staging failed for ledger=%s path=%s",
            tenant_id,
            relative_path,
        )
        return None


def _prepare_enrichment(
    expense_id: int,
    tenant_id: str,
    timezone_name: str | None,
    expected_row_version: int | None,
    *,
    raise_on_failure: bool,
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
        return _PreparedEnrichment(
            predecessor_row_version=predecessor_row_version,
            thumbnail_source_path=expense.image_path,
            thumbnail_needed=not expense.thumbnail_path,
            ocr_extractions=tuple(
                collect_auto_ocr_extractions(
                    expense,
                    timezone_name=timezone_name,
                    raise_on_failure=raise_on_failure,
                )
            ),
        )


def _apply_enrichment(
    expense_id: int,
    tenant_id: str,
    timezone_name: str | None,
    prepared: _PreparedEnrichment,
    staged_thumbnail: StagedThumbnail | None,
    before_apply: Callable[[], None] | None,
) -> PendingEnrichmentResult:
    from app.database import SessionLocal

    with SessionLocal() as db:
        expense = resolve_expense(db, tenant_id, expense_id, for_update=True)
        if expense is None or expense.status != "pending":
            return PendingEnrichmentResult(
                expense_id=expense_id,
                outcome="not_pending",
                row_version=expense.row_version if expense is not None else None,
            )
        if expense.row_version != prepared.predecessor_row_version:
            return PendingEnrichmentResult(
                expense_id=expense_id,
                outcome="conflict",
                row_version=expense.row_version,
            )
        _checkpoint(before_apply)
        resolve_write_capability(db)
        occ_snapshot = _enrichment_occ_snapshot(expense)
        for extraction in prepared.ocr_extractions:
            apply_ocr_result_and_append_fact(
                db,
                expense=expense,
                result=extraction.result,
                provider_name=extraction.provider_name,
                ocr_model=extraction.ocr_model,
                timezone_name=timezone_name,
            )
            _replace_ocr_draft_items_from_text(
                db,
                expense,
                extraction.result.raw_text,
                timezone_name=timezone_name,
            )
        if expense.category == "其他":
            classify_expense(db, expense)
        ensure_category_preference_for_name(
            db,
            tenant_id=expense.tenant_id,
            name=expense.category,
        )
        if expense.amount_cents is not None or expense.merchant or expense.expense_time is not None:
            mark_duplicate_status(db, expense)
        user_visible_changed = _enrichment_occ_snapshot(expense) != occ_snapshot
        if prepared.ocr_extractions or user_visible_changed:
            expense.updated_at = now_utc()
            bump_row_version(expense)
        if not expense.thumbnail_path and staged_thumbnail is not None:
            expense.thumbnail_path = publish_staged_thumbnail(staged_thumbnail)
        db.commit()
        db.refresh(expense)
        return PendingEnrichmentResult(
            expense_id=expense.id,
            outcome="updated" if user_visible_changed else "no_result",
            row_version=expense.row_version,
        )


def _failed_enrichment_result(
    expense_id: int,
    tenant_id: str,
) -> PendingEnrichmentResult:
    _record_background_failure("auto_enrich")
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
        )
        if isinstance(prepared, PendingEnrichmentResult):
            return prepared
        _checkpoint(before_apply)
        if prepared.thumbnail_needed:
            staged_thumbnail = _try_stage_thumbnail(
                prepared.thumbnail_source_path,
                tenant_id,
            )
        _checkpoint(before_apply)
        return _apply_enrichment(
            expense_id,
            tenant_id,
            timezone_name,
            prepared,
            staged_thumbnail,
            before_apply,
        )
    except _AUTO_ENRICHMENT_FAILURES:
        if raise_on_failure:
            _failed_enrichment_result(expense_id, tenant_id)
            raise
        return _failed_enrichment_result(expense_id, tenant_id)
    finally:
        discard_staged_thumbnail(staged_thumbnail)


__all__ = ["PendingEnrichmentResult", "enrich_pending_expense"]

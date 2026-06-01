from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    CategoriesResponse,
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
    ExpenseAcknowledgeItemsMismatchRequest,
    ExpenseConfirmRequest,
    ExpenseItemReplaceRequest,
    ExpenseItemsResponse,
    ExpenseManualCreateRequest,
    ExpenseMarkNotDuplicateRequest,
    ExpenseOcrRetryRequest,
    ExpenseRecognizeTextRequest,
    ExpenseRejectRequest,
    ExpenseResponse,
    ExpenseSplitReplaceRequest,
    ExpenseSplitsResponse,
    ExpenseUndoRequest,
    ExpenseUpdateRequest,
    MonthsResponse,
    NotificationDraftCreateRequest,
    PaginatedExpensesResponse,
    PendingCategorySuggestionResponse,
    PendingDuplicateCandidateResponse,
    StatusResponse,
    TagsResponse,
)
from app.services.expense_response_service import (
    expense_raw_text_by_id,
    expense_to_response,
    expenses_to_responses,
)
from app.services.expense_service import (
    batch_update_confirmed_expenses,
    confirm_expense,
    create_manual_expense,
    create_notification_draft,
    ensure_image_file,
    ensure_thumbnail_file,
    get_expense,
    list_confirmed,
    list_pending,
    mark_expense_not_duplicate,
    recognize_expense_text,
    reject_expense,
    retry_expense_ocr,
    undo_reject_expense,
    update_expense,
)
from app.services.expense_split_service import list_expense_splits, replace_expense_splits
from app.services.pending_suggestion_service import (
    record_pending_suggestion_event,
    suggestions_for_pending_expense,
)
from app.services.receipt_item_service import (
    acknowledge_items_sum_mismatch,
    list_expense_items,
    replace_expense_items,
)
from app.services.stats_service import export_confirmed_csv, list_categories, list_months
from app.services.tag_service import list_tags
from app.tenants import AuthContext

if TYPE_CHECKING:
    from app.models import Expense

router = APIRouter(
    prefix="/api/expenses",
    tags=["expenses"],
)


@router.get("/pending", response_model=list[ExpenseResponse])
def get_pending_expenses(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> list[ExpenseResponse]:
    expenses = list_pending(db, auth.tenant_id)
    raw_text_by_id = expense_raw_text_by_id(
        db, tenant_id=auth.tenant_id, expenses=expenses
    )
    items: list[ExpenseResponse] = []
    for expense in expenses:
        items.append(
            _expense_response_with_suggestions(
                db,
                tenant_id=auth.tenant_id,
                expense=expense,
                raw_text_by_id=raw_text_by_id,
            )
        )
    db.commit()
    return items


@router.post("/manual", response_model=ExpenseResponse)
def post_manual_expense(
    payload: ExpenseManualCreateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = create_manual_expense(db, payload, auth.tenant_id)
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.post("/notification-drafts", response_model=ExpenseResponse)
def post_notification_draft(
    payload: NotificationDraftCreateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = create_notification_draft(db, payload, auth.tenant_id)
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.get("/confirmed", response_model=PaginatedExpensesResponse)
def get_confirmed_expenses(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> PaginatedExpensesResponse:
    items, total = list_confirmed(
        db,
        tenant_id=auth.tenant_id,
        page=page,
        page_size=page_size,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone,
    )
    return PaginatedExpensesResponse(
        items=expenses_to_responses(db, tenant_id=auth.tenant_id, expenses=items),
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/confirmed/batch-update", response_model=ConfirmedExpenseBatchUpdateResponse)
def post_confirmed_expenses_batch_update(
    payload: ConfirmedExpenseBatchUpdateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ConfirmedExpenseBatchUpdateResponse:
    return batch_update_confirmed_expenses(db, tenant_id=auth.tenant_id, payload=payload)


@router.get("/categories", response_model=CategoriesResponse)
def get_expense_categories(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> CategoriesResponse:
    return CategoriesResponse(items=list_categories(db, auth.tenant_id))


@router.get("/tags", response_model=TagsResponse)
def get_expense_tags(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> TagsResponse:
    return TagsResponse(items=list_tags(db, auth.tenant_id))


@router.get("/months", response_model=MonthsResponse)
def get_expense_months(
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> MonthsResponse:
    return MonthsResponse(items=list_months(db, auth.tenant_id, timezone_name=timezone))


@router.get("/export.csv")
def get_expenses_csv(
    month: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> Response:
    content = "\ufeff" + export_confirmed_csv(
        db,
        tenant_id=auth.tenant_id,
        month=month,
        category=category,
        tag=tag,
        timezone_name=timezone,
    )
    filename = "ticketbox-expenses"
    if month:
        filename += f"-{month}"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


@router.get("/{expense_id}/items", response_model=ExpenseItemsResponse)
def get_expense_item_rows(
    expense_id: int,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ExpenseItemsResponse:
    return list_expense_items(db, expense_id, auth.tenant_id)


@router.put("/{expense_id}/items", response_model=ExpenseItemsResponse)
def put_expense_item_rows(
    expense_id: int,
    payload: ExpenseItemReplaceRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseItemsResponse:
    return replace_expense_items(db, expense_id, auth.tenant_id, payload)


@router.post(
    "/{expense_id}/items/acknowledge-mismatch",
    response_model=ExpenseItemsResponse,
    summary="原小票如此：把 items_sum_status 从 mismatch_known 迁移到 mismatch_acknowledged",
)
def acknowledge_expense_items_mismatch(
    expense_id: int,
    payload: ExpenseAcknowledgeItemsMismatchRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseItemsResponse:
    # ADR-0038 PR-2e: ``expected_updated_at`` token guards against a
    # user clicking "原小票如此" on a stale page after a peer edited
    # amount/items — without the token the service would flip a *new*
    # mismatch into ``mismatch_acknowledged``.
    return acknowledge_items_sum_mismatch(
        db,
        expense_id,
        auth.tenant_id,
        expected_updated_at=payload.expected_updated_at,
    )


@router.get("/{expense_id}/splits", response_model=ExpenseSplitsResponse)
def get_expense_split_rows(
    expense_id: int,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ExpenseSplitsResponse:
    return list_expense_splits(db, expense_id, auth.tenant_id)


@router.put("/{expense_id}/splits", response_model=ExpenseSplitsResponse)
def put_expense_split_rows(
    expense_id: int,
    payload: ExpenseSplitReplaceRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseSplitsResponse:
    return replace_expense_splits(
        db,
        expense_id,
        auth.tenant_id,
        payload,
        actor_account_id=auth.account_id,
    )


@router.get("/{expense_id}", response_model=ExpenseResponse)
def get_expense_detail(
    expense_id: int,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = get_expense(db, expense_id, auth.tenant_id)
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.get("/{expense_id}/image")
def get_expense_image(
    expense_id: int,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> FileResponse:
    path, media_type = ensure_image_file(db, expense_id, auth.tenant_id)
    return FileResponse(path=path, media_type=media_type)


@router.get("/{expense_id}/thumbnail")
def get_expense_thumbnail(
    expense_id: int,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> FileResponse:
    path, media_type = ensure_thumbnail_file(db, expense_id, auth.tenant_id)
    return FileResponse(path=path, media_type=media_type)


@router.patch("/{expense_id}", response_model=ExpenseResponse)
def patch_expense(
    expense_id: int,
    payload: ExpenseUpdateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = update_expense(db, expense_id, auth.tenant_id, payload)
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.post("/{expense_id}/confirm", response_model=ExpenseResponse)
def post_confirm_expense(
    expense_id: int,
    payload: ExpenseConfirmRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = confirm_expense(
        db,
        expense_id,
        auth.tenant_id,
        expected_updated_at=payload.expected_updated_at,
    )
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.post("/{expense_id}/reject", response_model=ExpenseResponse)
def post_reject_expense(
    expense_id: int,
    payload: ExpenseRejectRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = reject_expense(
        db,
        expense_id,
        auth.tenant_id,
        expected_updated_at=payload.expected_updated_at,
    )
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.post("/{expense_id}/undo", response_model=ExpenseResponse)
def post_undo_expense(
    expense_id: int,
    payload: ExpenseUndoRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    # ADR-0038 undo: restore a recently-rejected expense within the 5-minute
    # retention window. The ``expected_updated_at`` token (v1.3 PR-A) rejects
    # stale /undo from a cached banner for a row that's been re-rejected
    # since the banner was shown — without it, a late /undo from an iPhone
    # banner could un-do a NEW intentional reject. Past-window / wrong-status
    # / cross-tenant / missing-row / stale-token all collapse to one 404 so
    # the client just re-fetches state.
    #
    # Documented limitation (codex review P2): ``reject_expense`` clears
    # ``duplicate_of_id`` on other expenses that pointed at this one
    # (``duplicate_service.clear_duplicate_references_to``). Undo restores the
    # rejected row's own status/rejected_at/updated_at, but does NOT walk the
    # graph backwards to rediscover duplicates — those pointers stay ``None``.
    # If we ever want the symmetric inverse, we'd need a fresh duplicate-detection
    # pass against the unrejected target; flip
    # ``test_undo_does_not_restore_cleared_duplicate_references`` accordingly.
    expense = undo_reject_expense(
        db,
        expense_id,
        auth.tenant_id,
        payload.expected_updated_at,
        actor_account_id=auth.account_id,
    )
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.post("/{expense_id}/ocr/retry", response_model=ExpenseResponse)
def post_retry_ocr(
    expense_id: int,
    payload: ExpenseOcrRetryRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = retry_expense_ocr(
        db,
        expense_id,
        auth.tenant_id,
        expected_updated_at=payload.expected_updated_at,
    )
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.post("/{expense_id}/recognize-text", response_model=ExpenseResponse)
def post_recognize_text(
    expense_id: int,
    payload: ExpenseRecognizeTextRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = recognize_expense_text(db, expense_id, auth.tenant_id, payload)
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


@router.post(
    "/{expense_id}/suggestions/{decision_public_id}/accept",
    response_model=StatusResponse,
)
def post_accept_pending_suggestion(
    expense_id: int,
    decision_public_id: str,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> StatusResponse:
    get_expense(db, expense_id, auth.tenant_id)
    try:
        record_pending_suggestion_event(
            db,
            tenant_id=auth.tenant_id,
            expense_id=expense_id,
            decision_public_id=decision_public_id,
            event_type="accept",
            actor_account_id=auth.account_id,
        )
    except ValueError as exc:
        raise AppError("not_found", status_code=404) from exc
    db.commit()
    return StatusResponse()


@router.post(
    "/{expense_id}/suggestions/{decision_public_id}/reject",
    response_model=StatusResponse,
)
def post_reject_pending_suggestion(
    expense_id: int,
    decision_public_id: str,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> StatusResponse:
    get_expense(db, expense_id, auth.tenant_id)
    try:
        record_pending_suggestion_event(
            db,
            tenant_id=auth.tenant_id,
            expense_id=expense_id,
            decision_public_id=decision_public_id,
            event_type="reject",
            actor_account_id=auth.account_id,
        )
    except ValueError as exc:
        raise AppError("not_found", status_code=404) from exc
    db.commit()
    return StatusResponse()


@router.post("/{expense_id}/mark-not-duplicate", response_model=ExpenseResponse)
def post_mark_not_duplicate(
    expense_id: int,
    payload: ExpenseMarkNotDuplicateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    expense = mark_expense_not_duplicate(
        db,
        expense_id,
        auth.tenant_id,
        expected_updated_at=payload.expected_updated_at,
    )
    return expense_to_response(db, tenant_id=auth.tenant_id, expense=expense)


def _expense_response_with_suggestions(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    raw_text_by_id: dict[int, str] | None = None,
) -> ExpenseResponse:
    suggestions = suggestions_for_pending_expense(
        db, tenant_id=tenant_id, expense=expense
    )
    dto = expense_to_response(
        db,
        tenant_id=tenant_id,
        expense=expense,
        raw_text_by_id=raw_text_by_id,
    )
    if suggestions.category_suggestion is not None:
        dto.category_suggestion = PendingCategorySuggestionResponse(
            decision_public_id=suggestions.category_suggestion.decision_public_id,
            category=suggestions.category_suggestion.category,
            score=suggestions.category_suggestion.score,
            sample_size=suggestions.category_suggestion.sample_size,
            algorithm_version=suggestions.category_suggestion.algorithm_version,
        )
    dto.duplicate_candidates = [
        PendingDuplicateCandidateResponse(
            decision_public_id=item.decision_public_id,
            candidate_id=item.candidate_id,
            candidate_public_id=item.candidate_public_id,
            score=item.score,
            reasons=list(item.reasons),
            algorithm_version=item.algorithm_version,
        )
        for item in suggestions.duplicate_candidates
    ]
    return dto

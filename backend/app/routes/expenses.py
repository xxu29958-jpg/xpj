from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas import (
    CategoriesResponse,
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
    ExpenseItemReplaceRequest,
    ExpenseItemsResponse,
    ExpenseManualCreateRequest,
    ExpenseRecognizeTextRequest,
    ExpenseResponse,
    ExpenseSplitReplaceRequest,
    ExpenseSplitsResponse,
    ExpenseUpdateRequest,
    MonthsResponse,
    NotificationDraftCreateRequest,
    PaginatedExpensesResponse,
    TagsResponse,
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
    update_expense,
)
from app.services.expense_split_service import list_expense_splits, replace_expense_splits
from app.services.receipt_item_service import list_expense_items, replace_expense_items
from app.services.stats_service import export_confirmed_csv, list_categories, list_months
from app.services.tag_service import list_tags
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/expenses",
    tags=["expenses"],
)


@router.get("/pending", response_model=list[ExpenseResponse])
def get_pending_expenses(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> list[ExpenseResponse]:
    return list_pending(db, auth.tenant_id)


@router.post("/manual", response_model=ExpenseResponse)
def post_manual_expense(
    payload: ExpenseManualCreateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return create_manual_expense(db, payload, auth.tenant_id)


@router.post("/notification-drafts", response_model=ExpenseResponse)
def post_notification_draft(
    payload: NotificationDraftCreateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return create_notification_draft(db, payload, auth.tenant_id)


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
    return PaginatedExpensesResponse(items=items, page=page, page_size=page_size, total=total)


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
    return get_expense(db, expense_id, auth.tenant_id)


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
    return update_expense(db, expense_id, auth.tenant_id, payload)


@router.post("/{expense_id}/confirm", response_model=ExpenseResponse)
def post_confirm_expense(
    expense_id: int,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return confirm_expense(db, expense_id, auth.tenant_id)


@router.post("/{expense_id}/reject", response_model=ExpenseResponse)
def post_reject_expense(
    expense_id: int,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return reject_expense(db, expense_id, auth.tenant_id)


@router.post("/{expense_id}/ocr/retry", response_model=ExpenseResponse)
def post_retry_ocr(
    expense_id: int,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return retry_expense_ocr(db, expense_id, auth.tenant_id)


@router.post("/{expense_id}/recognize-text", response_model=ExpenseResponse)
def post_recognize_text(
    expense_id: int,
    payload: ExpenseRecognizeTextRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return recognize_expense_text(db, expense_id, auth.tenant_id, payload)


@router.post("/{expense_id}/mark-not-duplicate", response_model=ExpenseResponse)
def post_mark_not_duplicate(
    expense_id: int,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return mark_expense_not_duplicate(db, expense_id, auth.tenant_id)

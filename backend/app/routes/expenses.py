from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.auth import verify_app_token
from app.database import get_db
from app.schemas import (
    CategoriesResponse,
    ExpenseManualCreateRequest,
    ExpenseRecognizeTextRequest,
    ExpenseResponse,
    ExpenseUpdateRequest,
    MonthsResponse,
    PaginatedExpensesResponse,
)
from app.services.expense_service import (
    confirm_expense,
    create_manual_expense,
    ensure_thumbnail_file,
    export_confirmed_csv,
    get_expense,
    list_categories,
    list_confirmed,
    list_months,
    list_pending,
    mark_expense_not_duplicate,
    reject_expense,
    recognize_expense_text,
    retry_expense_ocr,
    update_expense,
)
from app.services.file_service import resolve_protected_image


router = APIRouter(
    prefix="/api/expenses",
    tags=["expenses"],
    dependencies=[Depends(verify_app_token)],
)


@router.get("/pending", response_model=list[ExpenseResponse])
def get_pending_expenses(db: Session = Depends(get_db)) -> list[ExpenseResponse]:
    return list_pending(db)


@router.post("/manual", response_model=ExpenseResponse)
def post_manual_expense(
    payload: ExpenseManualCreateRequest,
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return create_manual_expense(db, payload)


@router.get("/confirmed", response_model=PaginatedExpensesResponse)
def get_confirmed_expenses(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    month: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> PaginatedExpensesResponse:
    items, total = list_confirmed(db, page=page, page_size=page_size, month=month, category=category)
    return PaginatedExpensesResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/categories", response_model=CategoriesResponse)
def get_expense_categories(db: Session = Depends(get_db)) -> CategoriesResponse:
    return CategoriesResponse(items=list_categories(db))


@router.get("/months", response_model=MonthsResponse)
def get_expense_months(db: Session = Depends(get_db)) -> MonthsResponse:
    return MonthsResponse(items=list_months(db))


@router.get("/export.csv")
def get_expenses_csv(
    month: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    content = "\ufeff" + export_confirmed_csv(db, month=month, category=category)
    filename = "ticketbox-expenses"
    if month:
        filename += f"-{month}"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


@router.get("/{expense_id}/image")
def get_expense_image(expense_id: int, db: Session = Depends(get_db)) -> FileResponse:
    expense = get_expense(db, expense_id)
    path, media_type = resolve_protected_image(expense.image_path)
    return FileResponse(path=path, media_type=media_type)


@router.get("/{expense_id}/thumbnail")
def get_expense_thumbnail(expense_id: int, db: Session = Depends(get_db)) -> FileResponse:
    path, media_type = ensure_thumbnail_file(db, expense_id)
    return FileResponse(path=path, media_type=media_type)


@router.patch("/{expense_id}", response_model=ExpenseResponse)
def patch_expense(
    expense_id: int,
    payload: ExpenseUpdateRequest,
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return update_expense(db, expense_id, payload)


@router.post("/{expense_id}/confirm", response_model=ExpenseResponse)
def post_confirm_expense(expense_id: int, db: Session = Depends(get_db)) -> ExpenseResponse:
    return confirm_expense(db, expense_id)


@router.post("/{expense_id}/reject", response_model=ExpenseResponse)
def post_reject_expense(expense_id: int, db: Session = Depends(get_db)) -> ExpenseResponse:
    return reject_expense(db, expense_id)


@router.post("/{expense_id}/ocr/retry", response_model=ExpenseResponse)
def post_retry_ocr(expense_id: int, db: Session = Depends(get_db)) -> ExpenseResponse:
    return retry_expense_ocr(db, expense_id)


@router.post("/{expense_id}/recognize-text", response_model=ExpenseResponse)
def post_recognize_text(
    expense_id: int,
    payload: ExpenseRecognizeTextRequest,
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    return recognize_expense_text(db, expense_id, payload)


@router.post("/{expense_id}/mark-not-duplicate", response_model=ExpenseResponse)
def post_mark_not_duplicate(expense_id: int, db: Session = Depends(get_db)) -> ExpenseResponse:
    return mark_expense_not_duplicate(db, expense_id)

"""Web forms consume the existing subtask command and first receipt."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes._web_expense_return_context import ExpenseReturnContext, expense_return_form_context
from app.routes._web_expense_subtask import WebExpenseSubtaskForm, submit_web_expense_subtask, web_expense_subtask_form
from app.routes.web_common import LocalOnly, _list_ledger_options, _resolve_selected_ledger_id

router = APIRouter(prefix="/web", tags=["web"])


@router.post("/expenses/{expense_id}/items/save", response_class=HTMLResponse)
def web_items_save(
    expense_id: int, request: Request,
    item_name: list[str] = Form(default=[]), item_kind: list[str] = Form(default=[]),
    item_quantity: list[str] = Form(default=[]), item_unit_price_yuan: list[str] = Form(default=[]),
    item_amount_yuan: list[str] = Form(default=[]), item_category: list[str] = Form(default=[]),
    form: WebExpenseSubtaskForm = Depends(web_expense_subtask_form),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    return submit_web_expense_subtask(db, request, options, selected, expense_id, kind="items", form=form,
        lines={"item_name": item_name, "item_kind": item_kind, "item_quantity": item_quantity,
            "item_unit_price_yuan": item_unit_price_yuan, "item_amount_yuan": item_amount_yuan,
            "item_category": item_category}, return_context=return_context)


@router.post("/expenses/{expense_id}/items/acknowledge-mismatch", response_class=HTMLResponse)
def web_items_acknowledge_mismatch(
    expense_id: int, request: Request,
    form: WebExpenseSubtaskForm = Depends(web_expense_subtask_form),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    return submit_web_expense_subtask(db, request, options, selected, expense_id, kind="ack",
        form=form, lines={}, return_context=return_context)

"""Web forms consume the existing subtask command and first receipt."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes._web_expense_return_context import ExpenseReturnContext, expense_return_form_context
from app.routes._web_expense_subtask import WebExpenseSubtaskForm, submit_web_expense_subtask, web_expense_subtask_form
from app.routes.web_common import LocalOnly, _list_ledger_options, _resolve_selected_ledger_id

router = APIRouter(prefix="/web", tags=["web"])


@router.post("/expenses/{expense_id}/splits/save", response_class=HTMLResponse)
def web_splits_save(
    expense_id: int, request: Request,
    split_member_id: list[str] = Form(default=[]), split_amount_yuan: list[str] = Form(default=[]),
    split_note: list[str] = Form(default=[]),
    form: WebExpenseSubtaskForm = Depends(web_expense_subtask_form),
    return_context: ExpenseReturnContext = Depends(expense_return_form_context),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    return submit_web_expense_subtask(db, request, options, selected, expense_id, kind="splits", form=form,
        lines={"split_member_id": split_member_id, "split_amount_yuan": split_amount_yuan, "split_note": split_note},
        return_context=return_context)

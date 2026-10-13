"""Text matching shared by quick search and saved confirmed-stream queries."""

from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session

from app.models import Expense, OcrFact
from app.services.spending_contract_service import category_search_terms, merchant_search_terms


def _like_pattern(term: str) -> str:
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _matches_any_text(terms: list[str], *columns) -> object:
    patterns = [_like_pattern(term) for term in terms if term] or [_like_pattern("")]
    return or_(*(func.lower(func.coalesce(column, "")).like(pattern, escape="\\")
        for column in columns for pattern in patterns))


def matches_text(term: str, *columns) -> object:
    return _matches_any_text([term], *columns)


def matches_expense_search(db: Session, tenant_id: str, term: str) -> object:
    # Every retained OCR snapshot stays searchable, with the same ledger scope.
    ocr_match = exists().where(OcrFact.tenant_id == Expense.tenant_id,
        OcrFact.expense_id == Expense.id,
        func.lower(func.coalesce(OcrFact.raw_text, "")).like(_like_pattern(term), escape="\\"))
    return or_(
        _matches_any_text(merchant_search_terms(db, tenant_id=tenant_id, term=term), Expense.merchant),
        _matches_any_text(category_search_terms(term), Expense.category),
        matches_text(term, Expense.note, Expense.source, Expense.tags),
        ocr_match,
    )

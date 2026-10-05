"""One anchored reading of the existing expense and offset revision journals."""

from __future__ import annotations

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense, ExpenseOffsetFact, ExpenseOffsetRevision, ExpenseRevision
from app.schemas import ExpenseRevisionListResponse
from app.services.expense_offset_service import offset_revision_to_response
from app.services.expense_revision_service import revision_to_response


def _history_anchors(db: Session, tenant_id: str, expense_id: int) -> tuple[int, int]:
    # Capture both heads in one statement. Both journals append under the root
    # expense's write lock; later writes cannot enter either frozen prefix.
    offset_head = select(func.coalesce(func.max(ExpenseOffsetRevision.id), 0)).where(
        ExpenseOffsetRevision.tenant_id == tenant_id,
        ExpenseOffsetRevision.expense_id == expense_id,
    ).scalar_subquery()
    row = db.execute(select(Expense.fact_revision, offset_head).where(
        Expense.tenant_id == tenant_id, Expense.id == expense_id,
    )).first()
    if row is None:
        raise AppError("expense_not_found", status_code=404)
    return int(row[0]), int(row[1])


def _history_query(tenant_id: str, expense_id: int, revision: int, offset_id: int):
    return union_all(
        select(literal("expense").label("kind"), ExpenseRevision.id.label("id"),
            ExpenseRevision.created_at.label("created_at")).where(
                ExpenseRevision.tenant_id == tenant_id, ExpenseRevision.expense_id == expense_id,
                ExpenseRevision.revision_number <= revision),
        select(literal("offset").label("kind"), ExpenseOffsetRevision.id.label("id"),
            ExpenseOffsetRevision.created_at.label("created_at")).where(
                ExpenseOffsetRevision.tenant_id == tenant_id, ExpenseOffsetRevision.expense_id == expense_id,
                ExpenseOffsetRevision.id <= offset_id),
    ).subquery()


def _history_items(db: Session, tenant_id: str, expense_id: int, positions):
    expense_ids = [row.id for row in positions if row.kind == "expense"]
    offset_ids = [row.id for row in positions if row.kind == "offset"]
    expenses = {row.id: row for row in db.scalars(select(ExpenseRevision).where(
        ExpenseRevision.tenant_id == tenant_id, ExpenseRevision.expense_id == expense_id,
        ExpenseRevision.id.in_(expense_ids),
    ))}
    offsets = {revision.id: (revision, public_id) for revision, public_id in db.execute(
        select(ExpenseOffsetRevision, ExpenseOffsetFact.public_id).join(ExpenseOffsetFact,
            ExpenseOffsetFact.id == ExpenseOffsetRevision.offset_id).where(
                ExpenseOffsetRevision.tenant_id == tenant_id, ExpenseOffsetRevision.expense_id == expense_id,
                ExpenseOffsetFact.tenant_id == tenant_id, ExpenseOffsetFact.expense_id == expense_id,
                ExpenseOffsetRevision.id.in_(offset_ids)))
    }
    return [revision_to_response(db, expenses[row.id]) if row.kind == "expense" else
        offset_revision_to_response(db, offsets[row.id][0], offset_public_id=offsets[row.id][1])
        for row in positions]


def list_expense_fact_history(
    db: Session, *, tenant_id: str, expense_id: int, page: int, page_size: int,
    snapshot_revision: int | None = None, offset_snapshot_id: int | None = None,
) -> ExpenseRevisionListResponse:
    """Parent authorization stays with the caller; never publishes or edits facts."""
    root_head, offset_head = _history_anchors(db, tenant_id, expense_id)
    revision = root_head if snapshot_revision is None else min(root_head, snapshot_revision)
    offset_id = offset_head if offset_snapshot_id is None else min(offset_head, offset_snapshot_id)
    history = _history_query(tenant_id, expense_id, revision, offset_id)
    total = int(db.scalar(select(func.count()).select_from(history)) or 0)
    positions = db.execute(select(history).order_by(
        history.c.created_at.desc(), history.c.kind.desc(), history.c.id.desc(),
    ).offset((page - 1) * page_size).limit(page_size)).all()
    return ExpenseRevisionListResponse(
        items=_history_items(db, tenant_id, expense_id, positions), page=page, page_size=page_size,
        total=total, snapshot_revision=revision, offset_snapshot_id=offset_id,
    )

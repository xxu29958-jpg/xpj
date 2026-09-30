"""Read authoritative financial results in the existing isolated consumer journey."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, ExpenseOffsetFact, ExpenseOffsetRevision, ExpenseRevision, ExpenseSplit
from app.services.budget_service import get_monthly_budget
from app.services.expense_offset_service import expense_fact_bundle
from app.services.goal_service import list_goals
from app.services.stats_service import monthly_stats


def facts(ledger_id):
    with SessionLocal() as db:
        expenses = db.scalars(select(Expense).where(Expense.tenant_id == ledger_id).order_by(Expense.id)).all()
        if not expenses:
            return {"expenses": []}
        assert len(expenses) == 1, "The financial journey unexpectedly created another root expense"
        root = expenses[0]
        bundle = expense_fact_bundle(db, tenant_id=ledger_id, expense_id=root.id)
        month = root.accounting_date.strftime("%Y-%m")
        revisions = db.scalars(select(ExpenseRevision).where(ExpenseRevision.expense_id == root.id)
            .order_by(ExpenseRevision.revision_number)).all()
        offsets = db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == root.id)
            .order_by(ExpenseOffsetFact.id)).all()
        offset_history = db.scalars(select(ExpenseOffsetRevision).where(ExpenseOffsetRevision.expense_id == root.id)
            .order_by(ExpenseOffsetRevision.id)).all()
        splits = db.scalars(select(ExpenseSplit).where(ExpenseSplit.expense_id == root.id)
            .order_by(ExpenseSplit.id)).all()
        budget = get_monthly_budget(db, tenant_id=ledger_id, month=month)
        stats = monthly_stats(db, month, ledger_id)
        goals = list_goals(db, tenant_id=ledger_id, month=month)
        return {
            "expenses": [{"id": root.id, "public_id": root.public_id}],
            "id": root.id, "merchant": root.merchant, "amount": root.amount_cents,
            "currency": root.original_currency_code, "note": root.note, "category": root.category,
            "row_version": root.row_version, "date": root.accounting_date.isoformat(), "month": month,
            "image_hash": root.image_hash, "original_attached": bool(root.image_path),
            "net": bundle.financial_summary.lineage_home_net_cents,
            "revisions": [{"number": row.revision_number, "reason": row.reason,
                "before": row.before_snapshot, "after": row.after_snapshot} for row in revisions],
            "offsets": [{"public_id": row.public_id, "kind": row.kind, "status": row.status,
                "amount": row.amount_cents, "reason": row.reason, "row_version": row.row_version} for row in offsets],
            "offset_history": [{"public_id": row.public_id, "kind": row.change_kind,
                "before": row.before_snapshot, "after": row.after_snapshot} for row in offset_history],
            "splits": [{"public_id": row.public_id, "member_id": row.member_id,
                "amount": row.amount_cents, "note": row.note} for row in splits],
            "budget_configured": budget.configured, "budget_spent": budget.spent_amount_cents,
            "stats_spent": stats["total_amount_cents"],
            "goals": [{"name": row.name, "spent": row.spent_amount_cents} for row in goals],
        }

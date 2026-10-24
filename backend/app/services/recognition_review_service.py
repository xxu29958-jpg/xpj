"""Persist original-review suggestions independently of a financial command."""
from app.database import SessionLocal
from app.services.expense_service import get_expense
from app.services.learning_service import read_ocr_facts
from app.services.notification_time_service import notification_times_for_expenses
from app.services.recognition_field_memory import recall_field_choices
from app.services.recognition_field_service import recognition_fields
from app.services.recognition_memory_service import recall_time_choice
from app.services.recognition_time_service import recognition_amount_notes, recognition_time


def recognition_review_context(*, tenant_id: str, expense_id: int, actor_account_id: int | None) -> dict:
    # Recovery and error views run after the financial command has committed or
    # rolled back. This owner reads committed evidence and saves its exposure in
    # its own transaction; it cannot commit a caller's unsaved financial changes.
    with SessionLocal.begin() as db:
        expense = get_expense(db, expense_id, tenant_id)
        fact = read_ocr_facts(db, tenant_id=tenant_id, expenses=[expense]).get(expense.id)
        notification = notification_times_for_expenses(db, tenant_id=tenant_id,
            actor_account_id=actor_account_id, expense_public_ids=[expense.public_id]).get(expense.public_id)
        time = recall_time_choice(db, expense=expense, actor_account_id=actor_account_id,
            fact=fact, response=recognition_time(fact, notification=notification))
        fields = recall_field_choices(db, expense=expense, actor_account_id=actor_account_id,
            fact=fact, candidates=recognition_fields(fact))
        return {"recognition_time": time, "recognition_fields": fields,
            "recognition_notes": recognition_amount_notes(fact)}

"""Current identity and semantic eligibility for explicit repayment choices."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Debt, LedgerLearningEvent, Repayment, RepaymentDraft, RepaymentVoid
from app.services.learning_service._algorithm_registry import REPAYMENT_CHOICE
from app.services.time_service import ensure_utc


def normalize_repayment_label(label: str | None) -> str:
    return "".join((label or "").split()).casefold()


def repayment_source_context(draft: RepaymentDraft) -> dict:
    return {"public_id": draft.public_id, "tenant_id": draft.tenant_id, "actor_account_id": draft.created_by_account_id,
        "source": draft.source, "merchant_label": draft.merchant_label, "original_currency_code": draft.original_currency_code,
        "original_amount_minor": draft.original_amount_minor, "captured_at": ensure_utc(draft.captured_at).isoformat(),
        "committed_debt_public_id": draft.committed_debt_public_id,
        "committed_repayment_public_id": draft.committed_repayment_public_id,
        "source_expense_public_id": draft.source_expense_public_id}


def repayment_target_context(debt: Debt) -> dict:
    return {"public_id": debt.public_id, "tenant_id": debt.tenant_id, "counterparty_label": debt.counterparty_label,
        "counterparty_type": debt.counterparty_type, "direction": debt.direction, "source_type": debt.source_type,
        "home_currency_code": debt.home_currency_code, "principal_amount_cents": debt.principal_amount_cents}


def _current_repayment_identity(draft, debt, repayment, void_id, actor_account_id) -> bool:
    return (draft.status == "confirmed" and debt.status != "voided" and void_id is None
        and draft.created_by_account_id == actor_account_id and repayment.actor_account_id == actor_account_id)


def _source_result(event: LedgerLearningEvent, row) -> tuple[str, str, dict[str, str]]:
    import json

    if row is None:
        return "invalid", "原还款采集或对应欠款已不存在", {}
    draft, debt, repayment, void_id = row
    payload = json.loads(event.after_payload or "{}")
    if not _current_repayment_identity(draft, debt, repayment, void_id, event.actor_account_id):
        return "invalid", "原还款已撤销、改判，或不再属于原操作人", {}
    if not payload.get("_target_choice_explicit") or payload.get("_algorithm_version") != REPAYMENT_CHOICE.current_version:
        return "needs_review", "没有明确选择欠款的证据，未用于学习", {}
    source_matches = payload.get("_repayment_source") == repayment_source_context(draft)
    target_matches = payload.get("_repayment_target") == repayment_target_context(debt)
    fields = {"source": "valid" if source_matches else "superseded", "target": "valid" if target_matches else "superseded"}
    version = payload.get("_target_row_version")
    if not isinstance(version, int) or version > debt.row_version:
        return "needs_review", "缺少当时对应欠款的有效版本", fields
    if not source_matches or not target_matches:
        return "superseded", "还款来源或对应欠款的含义已有变化", fields
    return "valid", "本人明确选择的来源、欠款与还款事实仍一致", fields


def repayment_source_assessments(db: Session, *, tenant_id: str, events: list[LedgerLearningEvent]) -> dict:
    selected = [row for row in events if row.subject_kind == "repayment_draft" and row.signal_type == "repayment_choice"]
    if not selected:
        return {}
    rows = db.execute(select(RepaymentDraft, Debt, Repayment, RepaymentVoid.id)
        .join(Repayment, Repayment.public_id == RepaymentDraft.committed_repayment_public_id)
        .join(Debt, Debt.id == Repayment.debt_id)
        .outerjoin(RepaymentVoid, RepaymentVoid.repayment_id == Repayment.id)
        .where(RepaymentDraft.tenant_id == tenant_id, Debt.tenant_id == tenant_id,
            Debt.public_id == RepaymentDraft.committed_debt_public_id,
            RepaymentDraft.id.in_({event.subject_id for event in selected})))
    by_id = {row[0].id: row for row in rows}
    return {event.id: _source_result(event, by_id.get(event.subject_id)) for event in selected}

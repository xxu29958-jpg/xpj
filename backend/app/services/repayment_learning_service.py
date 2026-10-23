"""Explicit, reversible repayment case memory; no financial fact is learned into existence."""

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Debt, LedgerLearningEvent, RepaymentDraft
from app.services.learning_service import DecisionDraft, EventDraft, record_decision, record_event
from app.services.learning_service._algorithm_registry import REPAYMENT_CHOICE
from app.services.learning_service._policy import policy_enabled
from app.services.learning_service._repayment_sources import (
    normalize_repayment_label,
    repayment_source_context,
    repayment_target_context,
)
from app.services.learning_service._source_eligibility import _event_payload, eligible_feedback
from app.services.time_service import now_utc


@dataclass
class RepaymentMemory:
    cases: list[LedgerLearningEvent] = field(default_factory=list)
    decisions: dict[int, list[AlgorithmDecision]] = field(default_factory=dict)
    enabled: bool = False


def record_repayment_choice(db: Session, *, draft: RepaymentDraft, actor_account_id: int) -> None:
    debt = db.scalar(select(Debt).where(Debt.tenant_id == draft.tenant_id,
        Debt.public_id == draft.committed_debt_public_id))
    if debt is None or draft.status != "confirmed" or draft.created_by_account_id != actor_account_id:
        return
    entry = REPAYMENT_CHOICE
    decision = db.scalar(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == draft.tenant_id,
        AlgorithmDecision.subject_kind == "repayment_draft", AlgorithmDecision.subject_id == draft.id,
        AlgorithmDecision.decision_type == entry.decision_type, AlgorithmDecision.status == "dismissed")
        .order_by(AlgorithmDecision.id.desc()).limit(1))
    if decision is not None and json.loads(decision.output_payload).get("target_debt_public_id") == debt.public_id:
        decision.status = "accepted"
    event = record_event(db, EventDraft(tenant_id=draft.tenant_id, subject_kind="repayment_draft", subject_id=draft.id,
        decision_id=decision.id if decision is not None else None,
        actor_account_id=actor_account_id, event_type="manual_override", signal_type=entry.decision_type,
        signal_marker={"target_debt_public_id": debt.public_id}, after_payload={
            "_algorithm_version": entry.current_version, "_action_outcome": "committed", "_target_choice_explicit": True,
            "_target_row_version": debt.row_version, "_repayment_source": repayment_source_context(draft),
            "_repayment_target": repayment_target_context(debt), "_feedback_revision": 1}))
    event.retention_days = 0


def load_repayment_memory(db: Session, *, tenant_id: str, actor_account_id: int,
        drafts: list[RepaymentDraft]) -> RepaymentMemory:
    identifiers = [row.id for row in drafts if row.status == "pending"]
    if not identifiers:
        return RepaymentMemory()
    entry = REPAYMENT_CHOICE
    events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.actor_account_id == actor_account_id, LedgerLearningEvent.signal_type == entry.decision_type,
        LedgerLearningEvent.created_at <= now_utc()).order_by(LedgerLearningEvent.id.desc()).limit(200)))
    memory = RepaymentMemory(cases=eligible_feedback(db, tenant_id=tenant_id, events=events, actor_account_id=actor_account_id),
        enabled=policy_enabled(db, tenant_id=tenant_id, decision_type=entry.decision_type,
            version=entry.current_version, axis="new_suggestions"))
    decisions = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == tenant_id,
        AlgorithmDecision.subject_kind == "repayment_draft", AlgorithmDecision.subject_id.in_(identifiers),
        AlgorithmDecision.decision_type == entry.decision_type, AlgorithmDecision.algorithm_version == entry.current_version)
        .order_by(AlgorithmDecision.id.desc()))
    for row in decisions:
        memory.decisions.setdefault(row.subject_id, []).append(row)
    return memory


def _show_memory(db: Session, draft: RepaymentDraft, target: str, cases: list[LedgerLearningEvent], memory: RepaymentMemory) -> bool:
    key = hashlib.sha256(json.dumps([draft.public_id, draft.created_by_account_id, target,
        sorted(row.public_id for row in cases)]).encode()).hexdigest()
    for previous in memory.decisions.get(draft.id, []):
        if json.loads(previous.output_payload).get("memory_key") == key and previous.status != "superseded":
            return previous.status == "active"
    if not memory.enabled:
        return False
    entry = REPAYMENT_CHOICE
    decision = record_decision(db, DecisionDraft(tenant_id=draft.tenant_id, subject_kind="repayment_draft", subject_id=draft.id,
        decision_type=entry.decision_type, algorithm_version=entry.current_version,
        payload={"source_public_id": draft.public_id, "actor_account_id": draft.created_by_account_id,
            "target_debt_public_id": target, "memory_key": key,
            "case_public_ids": sorted(row.public_id for row in cases)}))
    memory.decisions.setdefault(draft.id, []).append(decision)
    return True


def _current_decisions(db: Session, draft: RepaymentDraft) -> list[AlgorithmDecision] | None:
    # All consumers serialize check/create on the existing source row. The second
    # reader must refresh decisions after the first commits, not use its old list.
    current = db.scalar(select(RepaymentDraft.id).where(RepaymentDraft.id == draft.id,
        RepaymentDraft.tenant_id == draft.tenant_id, RepaymentDraft.created_by_account_id == draft.created_by_account_id,
        RepaymentDraft.status == "pending").with_for_update())
    if current is None:
        return None
    return list(db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == draft.tenant_id,
        AlgorithmDecision.subject_kind == "repayment_draft", AlgorithmDecision.subject_id == draft.id,
        AlgorithmDecision.decision_type == REPAYMENT_CHOICE.decision_type,
        AlgorithmDecision.algorithm_version == REPAYMENT_CHOICE.current_version)
        .order_by(AlgorithmDecision.id.desc()).execution_options(populate_existing=True)))


def _retire_changed_decisions(decisions: list[AlgorithmDecision], targets: set[str], cases: list[LedgerLearningEvent]) -> None:
    case_ids = sorted(row.public_id for row in cases)
    for decision in decisions:
        payload = json.loads(decision.output_payload)
        if decision.status == "active" and (len(targets) != 1 or
                payload.get("target_debt_public_id") not in targets or payload.get("case_public_ids") != case_ids):
            decision.status = "superseded"
            decision.retention_days = REPAYMENT_CHOICE.retention_for_status("superseded")


def recalled_repayment_target(db: Session, *, draft: RepaymentDraft, feasible_ids: set[str], memory: RepaymentMemory) -> str | None:
    if not memory.cases and not memory.decisions.get(draft.id):
        return None
    decisions = _current_decisions(db, draft)
    if decisions is None:
        return None
    memory.decisions[draft.id] = decisions
    cases = []
    for event in memory.cases:
        source = _event_payload(event).get("_repayment_source", {})
        if (event.subject_id != draft.id and source.get("source") == draft.source
                and normalize_repayment_label(source.get("merchant_label")) == normalize_repayment_label(draft.merchant_label)
                and source.get("committed_debt_public_id") in feasible_ids):
            cases.append(event)
    targets = {_event_payload(row)["_repayment_source"]["committed_debt_public_id"] for row in cases}
    _retire_changed_decisions(decisions, targets, cases)
    if len(targets) != 1:
        return None
    target = targets.pop()
    return target if _show_memory(db, draft, target, cases, memory) else None

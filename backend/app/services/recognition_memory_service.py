"""Bounded, actor-scoped case recall; ranking never changes an accounting fact."""

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense, LedgerLearningEvent, OcrFact
from app.schemas._recognition_time import RecognitionTimeCandidate, RecognitionTimeResponse
from app.services.learning_service._algorithm_registry import RECOGNITION_TIME_CHOICE
from app.services.learning_service._policy import policy_enabled
from app.services.learning_service._source_eligibility import _event_payload, eligible_feedback
from app.services.notification_time_memory import notification_time_sources, recall_notification_time
from app.services.recognition_decision_service import reconcile_image_decision, source_learning_window_predicate
from app.services.recognition_evidence_context import time_candidate_key, time_case_key
from app.services.recognition_time_service import rank_time_origin
from app.services.time_service import now_utc


@dataclass
class TimeMemory:
    """One response's qualified cases and display decisions; never a cross-request cache."""

    cases: list[LedgerLearningEvent] = field(default_factory=list)
    decisions: dict[int, list[AlgorithmDecision]] = field(default_factory=dict)
    notification_sources: dict = field(default_factory=dict)
    new_suggestions_enabled: bool = False


def load_time_memory(db: Session, *, tenant_id: str, actor_account_id: int | None,
        expense_ids: list[int]) -> TimeMemory:
    if actor_account_id is None or not expense_ids:
        return TimeMemory()
    entry = RECOGNITION_TIME_CHOICE
    events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.actor_account_id == actor_account_id, LedgerLearningEvent.signal_type == entry.decision_type,
        LedgerLearningEvent.created_at <= now_utc(), source_learning_window_predicate())
        .order_by(LedgerLearningEvent.id.desc()).limit(200)))
    memory = TimeMemory(cases=eligible_feedback(db, tenant_id=tenant_id, events=events, actor_account_id=actor_account_id),
        notification_sources=notification_time_sources(db, tenant_id=tenant_id,
            actor_account_id=actor_account_id, expense_ids=expense_ids),
        new_suggestions_enabled=policy_enabled(db, tenant_id=tenant_id, decision_type=entry.decision_type,
            version=entry.current_version, axis="new_suggestions"))
    decisions = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == tenant_id,
        AlgorithmDecision.subject_kind == "expense", AlgorithmDecision.subject_id.in_(expense_ids),
        AlgorithmDecision.decision_type == entry.decision_type,
        AlgorithmDecision.algorithm_version == entry.current_version).order_by(AlgorithmDecision.id.desc()))
    for decision in decisions:
        memory.decisions.setdefault(decision.subject_id, []).append(decision)
    return memory


def _visible_memory(db: Session, *, expense: Expense, actor: int, fact: OcrFact, candidate,
        events: list, memory: TimeMemory) -> bool:
    entry = RECOGNITION_TIME_CHOICE
    payload = None
    if candidate is not None:
        key = hashlib.sha256(json.dumps([actor, fact.public_id, candidate.id,
            sorted(row.public_id for row in events)]).encode()).hexdigest()
        payload = {"memory_key": key, "actor_account_id": actor, "field": "expense_time",
            "candidate_id": candidate.id, "evidence_public_id": fact.public_id}
    return reconcile_image_decision(db, expense=expense, actor=actor, entry=entry, slot="expense_time",
        payload=payload, previous=memory.decisions.setdefault(expense.id, []), enabled=memory.new_suggestions_enabled)


def _matching_cases(expense: Expense, fact: OcrFact, memory: TimeMemory) -> list:
    key = time_case_key(fact)
    return [row for row in memory.cases if row.subject_id != expense.id and _event_payload(row).get("_case_key") == key
        and _event_payload(row).get("_source_context", {}).get("image_hash") != expense.image_hash]


def _agreed_candidate(matches: list, fact: OcrFact, response: RecognitionTimeResponse) -> RecognitionTimeCandidate | None:
    # New explicit revisions supersede the original case. Disagreement between
    # independent cases leaves the original ranking rather than inventing a vote.
    choices = {json.dumps(_event_payload(row).get("_candidate_key")) for row in matches}
    if len(choices) != 1:
        return None
    key = json.loads(choices.pop())
    candidates = json.loads(fact.evidence_json)["field_parse"]["candidates"]
    candidates = [item for item in candidates if item["field"] == "expense_time"
        and time_candidate_key(fact.raw_text, item) == key]
    if len(candidates) != 1:
        return None
    return next((item for item in response.candidates if item.id == candidates[0]["id"]
        and item.evidence_public_id == fact.public_id and item.can_apply), None)


def recall_time_choice(db: Session, *, expense: Expense, actor_account_id: int | None,
        fact: OcrFact | None, response: RecognitionTimeResponse | None,
        memory: TimeMemory | None = None) -> RecognitionTimeResponse | None:
    if actor_account_id is None or expense.status != "pending":
        return response
    if memory is None:
        memory = load_time_memory(db, tenant_id=expense.tenant_id, actor_account_id=actor_account_id, expense_ids=[expense.id])
    available = fact is not None and response is not None and expense.image_hash and len(response.candidates) >= 2
    matches = _matching_cases(expense, fact, memory) if available else []
    chosen = _agreed_candidate(matches, fact, response) if available else None
    if _visible_memory(db, expense=expense, actor=actor_account_id, fact=fact, candidate=chosen, events=matches, memory=memory):
        chosen = chosen.model_copy(update={"explanation": chosen.explanation + " 你曾在同类原件中明确选择这一处时间。"})
        response = rank_time_origin(response, chosen)
    return recall_notification_time(db, expense=expense, actor=actor_account_id, response=response, memory=memory)

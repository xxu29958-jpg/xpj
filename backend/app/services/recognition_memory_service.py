"""Bounded, actor-scoped case recall; ranking never changes an accounting fact."""

import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense, LedgerLearningEvent, OcrFact
from app.schemas._recognition_time import RecognitionTimeCandidate, RecognitionTimeResponse
from app.services.learning_service._algorithm_registry import RECOGNITION_TIME_CHOICE
from app.services.learning_service._policy import policy_enabled
from app.services.learning_service._source_eligibility import _event_payload, eligible_feedback
from app.services.time_service import now_utc


def time_case_key(fact: OcrFact) -> str:
    evidence = json.loads(fact.evidence_json or "{}")
    # Keep labels, merchant and line order. Replacing digits generalizes only
    # within this narrow source pattern; a layout/text change gets a new case.
    text = re.sub(r"\d+", "#", fact.raw_text or "")
    blocks = evidence.get("blocks", [])
    width, height = evidence.get("width"), evidence.get("height")
    geometry = ([[round(x / width, 1), round(y / height, 1)] for block in blocks for x, y in block.get("box", [])]
        if blocks and width and height else [])
    return hashlib.sha256(json.dumps([evidence.get("field_parse", {}).get("version"), text, geometry],
        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def time_candidate_key(raw_text: str, candidate: dict) -> list:
    lines = sorted({raw_text.count("\n", 0, start) for start, _ in candidate["raw_spans"]})
    return [lines, candidate.get("role"), candidate.get("precision"), candidate.get("source"),
        candidate.get("timezone_name"), candidate.get("review_reason")]


def _visible_memory(db: Session, *, expense: Expense, actor: int, fact: OcrFact, candidate, events: list) -> bool:
    from app.services.learning_service import DecisionDraft, record_decision

    entry = RECOGNITION_TIME_CHOICE
    key = hashlib.sha256(json.dumps([actor, fact.public_id, candidate.id,
        sorted(row.public_id for row in events)]).encode()).hexdigest()
    decisions = db.scalars(select(AlgorithmDecision).where(AlgorithmDecision.tenant_id == expense.tenant_id,
        AlgorithmDecision.subject_kind == "expense", AlgorithmDecision.subject_id == expense.id,
        AlgorithmDecision.decision_type == entry.decision_type,
        AlgorithmDecision.algorithm_version == entry.current_version).order_by(AlgorithmDecision.id.desc()))
    for decision in decisions:
        if json.loads(decision.output_payload).get("memory_key") == key:
            return decision.status == "active"
    if not policy_enabled(db, tenant_id=expense.tenant_id, decision_type=entry.decision_type,
            version=entry.current_version, axis="new_suggestions"):
        return False
    record_decision(db, DecisionDraft(tenant_id=expense.tenant_id, decision_type=entry.decision_type,
        algorithm_version=entry.current_version, subject_kind="expense", subject_id=expense.id,
        subject_public_id=expense.public_id, payload={"memory_key": key, "actor_account_id": actor,
            "candidate_id": candidate.id, "evidence_public_id": fact.public_id}))
    return True


def _matching_cases(db: Session, expense: Expense, actor_account_id: int, fact: OcrFact) -> list:
    entry = RECOGNITION_TIME_CHOICE
    events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == expense.tenant_id,
        LedgerLearningEvent.actor_account_id == actor_account_id, LedgerLearningEvent.signal_type == entry.decision_type,
        LedgerLearningEvent.subject_id != expense.id, LedgerLearningEvent.created_at <= now_utc())
        .order_by(LedgerLearningEvent.id.desc()).limit(200)))
    events = eligible_feedback(db, tenant_id=expense.tenant_id, events=events, actor_account_id=actor_account_id)
    key = time_case_key(fact)
    return [row for row in events if _event_payload(row).get("_case_key") == key
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
        fact: OcrFact | None, response: RecognitionTimeResponse | None) -> RecognitionTimeResponse | None:
    if (actor_account_id is None or fact is None or response is None or expense.status != "pending"
            or not expense.image_hash or len(response.candidates) < 2):
        return response
    matches = _matching_cases(db, expense, actor_account_id, fact)
    chosen = _agreed_candidate(matches, fact, response)
    if chosen is None:
        return response
    if not _visible_memory(db, expense=expense, actor=actor_account_id, fact=fact, candidate=chosen, events=matches):
        return response
    chosen = chosen.model_copy(update={"explanation": chosen.explanation + " 你曾在同类原件中明确选择这一处时间。"})
    return response.model_copy(update={"candidates": [chosen] + [item for item in response.candidates if item.id != chosen.id]})

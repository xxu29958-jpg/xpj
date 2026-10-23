"""Eligibility of existing feedback; this module does not change scoring or train a model."""

import json
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense, ExpenseOffsetFact, LedgerLearningEvent
from app.services.learning_service._policy import policy_enabled
from app.services.time_service import ensure_utc, now_utc


def effective_expense_predicate():
    return ~select(ExpenseOffsetFact.id).where(ExpenseOffsetFact.tenant_id == Expense.tenant_id,
        ExpenseOffsetFact.expense_id == Expense.id, ExpenseOffsetFact.kind == "reversal",
        ExpenseOffsetFact.status == "active").exists()


def source_context(expense):
    return {"public_id": expense.public_id, "row_version": expense.row_version,
        "tenant_id": expense.tenant_id, "status": expense.status,
        "merchant": (expense.merchant or "").strip().casefold(), "category": expense.category,
        "amount_cents": expense.amount_cents, "original_currency_code": expense.original_currency_code,
        "original_amount_minor": expense.original_amount_minor,
        "expense_time": ensure_utc(expense.expense_time).isoformat() if expense.expense_time else None,
        "image_hash": expense.image_hash,
        "accounting_date": expense.accounting_date.isoformat() if expense.accounting_date else None,
        "time_precision": expense.time_precision, "source_timezone": expense.source_timezone,
        "source_utc_offset_seconds": expense.source_utc_offset_seconds,
        "user_local_date": expense.user_local_date.isoformat() if expense.user_local_date else None}


def decision_context(expense, decision_type, actor_account_id):
    snapshot = source_context(expense)
    required = ("public_id", "row_version", "merchant", "category") if decision_type == "category_suggestion" else (
        "public_id", "row_version", "merchant", "amount_cents", "original_currency_code",
        "original_amount_minor", "expense_time", "image_hash", "accounting_date", "time_precision", "source_timezone")
    return {**{name: snapshot[name] for name in required}, "actor_account_id": actor_account_id}


def capture_feedback_context(db, draft):
    payload = dict(draft.after_payload or {})
    if draft.subject_kind == "expense" and draft.subject_id is not None:
        expense = db.scalar(select(Expense).where(Expense.tenant_id == draft.tenant_id, Expense.id == draft.subject_id))
        if expense is not None:
            # CAS commands can leave an older object in the identity map. Freeze
            # the successful transaction's actual version, without committing it.
            db.flush()
            db.refresh(expense)
            payload["_source_context"] = source_context(expense)
    return payload


def feedback_sources(db, *, tenant_id, events):
    identifiers = {row.subject_id for row in events if row.subject_kind == "expense"}
    identifiers.update(payload.get("candidate_id") for row in events
        if row.signal_type == "duplicate_candidate" for payload in [_event_payload(row)]
        if isinstance(payload.get("candidate_id"), int))
    sources = {row.id: row for row in db.scalars(select(Expense).where(Expense.tenant_id == tenant_id,
        Expense.id.in_(identifiers)))} if identifiers else {}
    reversed_ids = set(db.scalars(select(ExpenseOffsetFact.expense_id).where(
        ExpenseOffsetFact.tenant_id == tenant_id, ExpenseOffsetFact.expense_id.in_(identifiers),
        ExpenseOffsetFact.kind == "reversal", ExpenseOffsetFact.status == "active"))) if identifiers else set()
    return sources, reversed_ids


def _event_payload(event: LedgerLearningEvent) -> dict:
    try:
        payload = json.loads(event.after_payload or "{}")
        return payload if isinstance(payload, dict) else {}
    except (TypeError, ValueError):
        return {}


def _discarded_source_changed(expense: Expense, context: dict) -> bool:
    return (expense.status != "rejected" or context.get("status") != "rejected"
        or context.get("row_version") != expense.row_version)


def _source_snapshot_changed(expense: Expense, context: dict, fields: dict, required: tuple[str, ...]) -> bool:
    return (context.get("public_id") != expense.public_id
        or context["row_version"] > expense.row_version or any(fields[name] != "valid" for name in required))


def _source_qualification(expense: Expense | None, context: object, *, tenant_id: str,
        reversed_ids: set[int], required: tuple[str, ...], deliberately_discarded: bool = False) -> tuple[str, str, dict[str, str]]:
    if expense is None or expense.tenant_id != tenant_id:
        return "invalid", "来源账目不存在或不在本账本", {}
    if not isinstance(context, dict):
        return "needs_review", "缺少原字段证据，未用于学习", {}
    current = source_context(expense)
    fields = {name: ("valid" if context.get(name) == current[name] else "superseded")
        for name in ("merchant", "category", "amount_cents", "original_currency_code",
            "original_amount_minor", "expense_time", "image_hash", "accounting_date", "time_precision", "source_timezone",
            "source_utc_offset_seconds", "user_local_date")}
    if expense.id in reversed_ids or (expense.status == "rejected" and not deliberately_discarded):
        return "invalid", "消费已撤销或已冲正；商家等未变字段仍保留原反馈证据", fields
    if deliberately_discarded and _discarded_source_changed(expense, context):
        return "superseded", "当时选择移出的账目后来又有变化", fields
    if not isinstance(context.get("row_version"), int) or any(name not in context for name in required):
        return "needs_review", "缺少原版本或此字段的完整证据，未用于学习", fields
    if _source_snapshot_changed(expense, context, fields, required):
        return "superseded", "此建议依赖的来源字段已更正", fields
    return "valid", "来源与此字段反馈仍一致", fields


def _event_qualification(event: LedgerLearningEvent, latest_ids: set[int] | None) -> tuple[str, str, dict[str, str]] | None:
    """Only explicit, current and retained events can qualify their sources."""
    if event.event_type == "withdraw":
        return "invalid", "这条反馈已撤回；原判断保留但不再用于学习", {}
    if event.actor_account_id is None:
        return "needs_review", "缺少明确操作人的证据，未用于学习", {}
    if latest_ids is not None and event.id not in latest_ids:
        return "superseded", "已有同一操作人对这一来源的后续反馈；保留原记录", {}
    if event.event_type not in {"accept", "reject", "edit", "manual_override"}:
        return "needs_review", "未记录明确选择，不能作为学习标签", {}
    if event.retention_days > 0 and ensure_utc(event.created_at) + timedelta(days=event.retention_days) < now_utc():
        return "invalid", "反馈已超过保留期限，不再用于学习", {}
    return None


def _choice_qualification(event: LedgerLearningEvent, payload: dict) -> tuple[str, str, dict] | None:
    if event.signal_type == "category_suggestion" and (
            payload.get("_category_intent") == "one_off"
            or (event.event_type == "manual_override" and payload.get("_category_intent") != "manual")):
        return "needs_review", "保留单笔分类或未注明用途的历史修改；不当作个人偏好样本", {}
    if event.signal_type in {"recognition_time_choice", "recognition_field_choice"} and not payload.get("_learning_qualified"):
        return "needs_review", "保留原件纠正或记账意图；没有把普通修改当作候选选择标签", {}
    if event.signal_type == "duplicate_candidate" and (
            payload.get("_relation") not in {"same", "distinct"} or payload.get("_action_outcome") != "committed"):
        return "needs_review", "未记录明确配对关系及成功结果，未用于学习", {}
    return None


def feedback_eligibility(event: LedgerLearningEvent, expense: Expense | None, reversed_ids: set[int],
        candidate: Expense | None = None, latest_ids: set[int] | None = None) -> tuple[str, str, dict[str, str]]:
    """Both sides use the same source test; originals are never rewritten."""
    payload = _event_payload(event)
    event_result = _event_qualification(event, latest_ids) or _choice_qualification(event, payload)
    if event_result is not None:
        return event_result
    paired = event.signal_type == "duplicate_candidate"
    resolution = payload.get("_resolution") if paired and payload.get("_relation") == "same" else None
    required = ("merchant", "category") if event.signal_type == "category_suggestion" else (
        "merchant", "amount_cents", "original_currency_code", "original_amount_minor", "expense_time", "image_hash",
        "accounting_date", "time_precision", "source_timezone")
    if event.signal_type == "recognition_time_choice":
        required = ("expense_time", "image_hash", "time_precision", "source_timezone", "accounting_date",
            "source_utc_offset_seconds", "user_local_date")
    if event.signal_type == "recognition_field_choice":
        required = (("merchant", "image_hash") if payload.get("field") == "merchant" else
            ("amount_cents", "original_currency_code", "original_amount_minor", "image_hash"))
    result = _source_qualification(expense, payload.get("_source_context"), tenant_id=event.tenant_id,
        reversed_ids=reversed_ids, required=required, deliberately_discarded=resolution == "keep_candidate")
    if result[0] != "valid" or event.signal_type != "duplicate_candidate":
        return result
    context = payload.get("_candidate_context")
    if not isinstance(context, dict):
        return "needs_review", "缺少配对另一侧的原始版本与证据，未用于学习", result[2]
    paired = _source_qualification(candidate, context, tenant_id=event.tenant_id,
        reversed_ids=reversed_ids, required=required, deliberately_discarded=resolution == "keep_subject")
    fields = {**result[2], **{"candidate_" + name: value for name, value in paired[2].items()}}
    return paired[0], "配对另一侧：" + paired[1], fields


def _latest_feedback_ids(db, *, tenant_id: str, events: list[LedgerLearningEvent]) -> set[int]:
    identifiers = {event.subject_id for event in events if event.subject_kind in {"expense", "repayment_draft"}}
    if not identifiers:
        return set()
    rows = db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.subject_kind.in_(("expense", "repayment_draft")), LedgerLearningEvent.subject_id.in_(identifiers),
        LedgerLearningEvent.signal_type.in_(("category_suggestion", "duplicate_candidate", "recognition_time_choice", "recognition_field_choice", "repayment_choice")),
        LedgerLearningEvent.event_type.in_(("accept", "reject", "edit", "manual_override", "withdraw")),
        LedgerLearningEvent.created_at <= now_utc()).order_by(LedgerLearningEvent.id.desc()))
    current = {}
    for row in rows:
        pair = _event_payload(row).get("candidate_id") if row.signal_type == "duplicate_candidate" else None
        if row.signal_type == "recognition_field_choice":
            pair = _event_payload(row).get("field")
        current.setdefault((row.actor_account_id, row.subject_kind, row.subject_id, row.signal_type, pair), row.id)
    return set(current.values())


def eligible_feedback(db, *, tenant_id, events, actor_account_id):
    if actor_account_id is None:
        return []
    events = [row for row in events if row.tenant_id == tenant_id and row.actor_account_id == actor_account_id]
    assessments = feedback_assessments(db, tenant_id=tenant_id, events=events)
    return [row for row in events if assessments[row.id][0] == "valid"]


def _current_time_facts(db: Session, tenant_id: str, events: list[LedgerLearningEvent], sources: dict) -> dict:
    from app.services.learning_service import read_ocr_facts

    image_subjects = {row.subject_id for row in events if row.signal_type in {"recognition_time_choice", "recognition_field_choice"}
        and _event_payload(row).get("source") == "image"}
    return read_ocr_facts(db, tenant_id=tenant_id,
        expenses=[row for key, row in sources.items() if key in image_subjects])


def _image_choice_replaced(event: LedgerLearningEvent, payload: dict, facts: dict) -> bool:
    if event.signal_type not in {"recognition_time_choice", "recognition_field_choice"} or payload.get("source") != "image":
        return False
    fact = facts.get(event.subject_id)
    return fact is None or fact.public_id != payload.get("evidence_public_id")


def _current_category_contexts(db, tenant_id, events, sources):
    from app.services.learning_service._category_context import category_contexts
    category_ids = {row.subject_id for row in events if row.signal_type == "category_suggestion"
        and "_category_context" in _event_payload(row)}
    return category_contexts(db, tenant_id=tenant_id,
        expenses=[row for key, row in sources.items() if key in category_ids])


def _category_context_replaced(event, payload, contexts):
    return (event.signal_type == "category_suggestion" and "_category_context" in payload
        and payload["_category_context"] != contexts.get(event.subject_id))


def _apply_feedback_controls(public_id, assessment, *, withdrawn, training_enabled):
    status, reason, fields = assessment
    if public_id in withdrawn:
        return "invalid", "这次选择已明确撤回；原记录仍保留", fields
    if status == "valid" and not training_enabled:
        return "quarantined", "此版本反馈已隔离，不参与新建议", fields
    return status, reason, fields


def _changed_feedback_source(event, payload, image_facts, category_sources, captures, time_captures) -> str | None:
    if _image_choice_replaced(event, payload, image_facts):
        return "原件识别证据已有更新；保留当时选择，不再用于新建议"
    if _category_context_replaced(event, payload, category_sources):
        return "分类所依据的用途、商品或账户已有变化，保留原选择但不再用于新建议"
    if event.signal_type == "recognition_field_choice" and payload.get("source") == "notification" and (
            not payload.get("_capture_context") or payload["_capture_context"] != captures.get(payload.get("evidence_public_id"))):
        return "通知来源或核对版本已变化；保留当时选择，不再用于新建议"
    if event.signal_type == "recognition_time_choice" and payload.get("source") == "notification" and (
            not payload.get("_capture_context") or payload["_capture_context"] != time_captures.get(payload.get("evidence_public_id"))):
        return "通知时间来源或核对版本已变化；保留当时选择，不再用于新建议"
    return None


def feedback_assessments(db: Session, *, tenant_id: str,
        events: list[LedgerLearningEvent]) -> dict[int, tuple[str, str, dict[str, str]]]:
    from app.services.learning_service._repayment_sources import repayment_source_assessments
    from app.services.recognition_evidence_context import notification_evidence_contexts

    sources, reversed_ids = feedback_sources(db, tenant_id=tenant_id, events=events)
    repayments = repayment_source_assessments(db, tenant_id=tenant_id, events=events)
    image_facts = _current_time_facts(db, tenant_id, events, sources)
    captures, time_captures = notification_evidence_contexts(db, tenant_id=tenant_id,
        payloads=[_event_payload(row) for row in events])
    category_sources = _current_category_contexts(db, tenant_id, events, sources)
    latest = _latest_feedback_ids(db, tenant_id=tenant_id, events=events)
    decisions = {row.id: row.algorithm_version for row in db.scalars(select(AlgorithmDecision).where(
        AlgorithmDecision.tenant_id == tenant_id, AlgorithmDecision.id.in_({row.decision_id for row in events})))}
    withdrawn = {_event_payload(row).get("_withdraws_event_public_id") for row in db.scalars(select(LedgerLearningEvent).where(
        LedgerLearningEvent.tenant_id == tenant_id, LedgerLearningEvent.event_type == "withdraw",
        LedgerLearningEvent.created_at <= now_utc()))}
    policies, results = {}, {}
    for row in events:
        payload = _event_payload(row)
        version = payload.get("_algorithm_version") or decisions.get(row.decision_id) or "unversioned"
        key = (row.signal_type, version)
        if key not in policies:
            policies[key] = policy_enabled(db, tenant_id=tenant_id, decision_type=key[0], version=key[1], axis="training")
        if row.id in repayments:
            status, reason, fields = _event_qualification(row, latest) or repayments[row.id]
        else:
            status, reason, fields = feedback_eligibility(row, sources.get(row.subject_id), reversed_ids,
                sources.get(payload.get("candidate_id")), latest)
        if status == "valid" and (changed := _changed_feedback_source(row, payload, image_facts, category_sources, captures, time_captures)):
            status, reason = "superseded", changed
        results[row.id] = _apply_feedback_controls(row.public_id, (status, reason, fields),
            withdrawn=withdrawn, training_enabled=policies[key])
    return results


def feedback_impact_preview(db, *, tenant_id):
    # No data rewrite, no new label inferred from historical defaults. The admin
    # sees counts; original individual feedback stays in its existing history.
    events = list(db.scalars(select(LedgerLearningEvent).where(LedgerLearningEvent.tenant_id == tenant_id,
        LedgerLearningEvent.subject_kind.in_(("expense", "repayment_draft")),
        LedgerLearningEvent.signal_type.in_(("category_suggestion", "duplicate_candidate", "recognition_time_choice", "recognition_field_choice", "repayment_choice")))))
    counts = Counter(result[0] for result in feedback_assessments(db, tenant_id=tenant_id, events=events).values())
    return {name: counts[name] for name in ("valid", "invalid", "superseded", "needs_review", "quarantined")}

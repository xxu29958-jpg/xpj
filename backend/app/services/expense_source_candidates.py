"""Publish independent drafts from every card, under the source's transaction."""

import hashlib
import re
from dataclasses import asdict, dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense, ExpenseSourceCandidate
from app.services.file_service import save_original_replenishment_bytes
from app.services.ocr_service import OcrResult
from app.services.ocr_service._draft_fields import ocr_draft_fields
from app.services.original_read_service import read_original_snapshot
from app.services.receipt_parse_common import FIELD_PARSE_VERSION
from app.services.time_service import now_utc


@dataclass(frozen=True)
class SourceEventDraft:
    expense: Expense
    result: OcrResult
    fresh: bool


def stage_source_event_drafts(db: Session, *, expense: Expense, result: OcrResult, parsed,
        provider_name: str, ocr_model: str | None, use_source_draft: bool = True) -> list[SourceEventDraft]:
    """One source lock serializes retries; existing siblings are never edited here.

    The original upload remains the first candidate. Each additional candidate
    owns a verified copy of its evidence, so existing per-expense cleanup cannot
    remove another candidate's original. A later transaction rollback leaves
    unreferenced copies to the existing orphan-upload owner, never dangling DB
    references or partially published candidates.
    """
    assigned = db.scalar(select(ExpenseSourceCandidate).where(
        ExpenseSourceCandidate.tenant_id == expense.tenant_id, ExpenseSourceCandidate.expense_id == expense.id))
    source_id = assigned.source_expense_id if assigned else expense.id
    source = db.scalar(select(Expense).where(Expense.id == source_id, Expense.tenant_id == expense.tenant_id).with_for_update())
    previous = list(db.scalars(select(ExpenseSourceCandidate).where(
        ExpenseSourceCandidate.tenant_id == expense.tenant_id, ExpenseSourceCandidate.source_expense_id == source_id)))
    by_key = {row.event_key: row for row in previous}
    extraction_hash = hashlib.sha256(result.raw_text.encode()).hexdigest()
    staged = []
    reuse_source = use_source_draft and (expense.amount_cents is None or "amount_cents" in ocr_draft_fields(expense))
    for index, event in enumerate(parsed.events):
        row = by_key.get(event["id"])
        fresh = row is None
        target = expense if reuse_source and not previous and index == 0 else None
        if row is not None:
            if row.expense_id != expense.id or not use_source_draft:
                continue  # Already independently published; a retry of this draft cannot edit its sibling.
            target = expense
        if target is None:
            target = _stage_child(db, source, evidence_owner=expense)
        event_result, evidence = _event_result(result, event, source, provider_name, ocr_model)
        evidence["candidates"] = [asdict(item) for item in parsed.candidates if item.event_id == event["id"]]
        if fresh:
            db.add(ExpenseSourceCandidate(tenant_id=source.tenant_id, source_expense_id=source.id,
                expense_id=target.id, event_key=event["id"], extraction_hash=extraction_hash,
                event_index=index, evidence=evidence))
            db.flush()
        staged.append(SourceEventDraft(target, event_result, fresh))
    return staged


def _event_result(result, event, source, provider_name, ocr_model):
    start, end = event["raw_spans"][0]
    original = result.evidence or {}
    blocks = original.get("blocks") or []
    evidence = {"source_expense_public_id": source.public_id, "source_image_sha256": source.image_hash,
        "source_text": result.raw_text, "event_key": event["id"], "raw_spans": event["raw_spans"],
        "block_indices": event["block_indices"], "provider": provider_name, "model": ocr_model,
        "parser_version": FIELD_PARSE_VERSION,
        "source_app": _source_app(result.raw_text[:start] + result.raw_text[start:end].splitlines()[0]),
        "time_fragments": [{"literal": match.group(), "raw_span": [start + match.start(), start + match.end()],
            "precision": "time_only", "role": "notification_display", "date": None}
            for match in re.finditer(r"(?<![\d:])(?:[01]?\d|2[0-3]):[0-5]\d(?![:\d])", result.raw_text[start:end])]}
    scoped = {**original, "source_event": evidence,
        "blocks": [blocks[index] for index in event["block_indices"]]}
    # Provider summary fields may describe a different card. Each card is parsed independently.
    return OcrResult(raw_text=result.raw_text[start:end], confidence=result.confidence, evidence=scoped), evidence


def _source_app(text: str) -> str | None:
    for line in reversed(text.splitlines()):
        for app, label in (("alipay", "支付宝"), ("wechat", "微信")):
            if re.match(rf"^{label}(?:支付)?(?:[·•\s(（]|$)", line.strip()):
                return app
    return None


def _stage_child(db, source, *, evidence_owner):
    saved = None
    if evidence_owner.image_path is not None and evidence_owner.image_deleted_at is None:
        with read_original_snapshot(relative_path=evidence_owner.image_path, tenant_id=source.tenant_id,
                expected_sha256=evidence_owner.image_hash) as original:
            saved = save_original_replenishment_bytes(original.path.read_bytes(), tenant_id=source.tenant_id,
                expected_sha256=original.sha256, filename=original.path.name, content_type=original.media_type)
            saved = replace(saved, image_evidence=evidence_owner.image_evidence)
    now = now_utc()
    child = Expense(tenant_id=source.tenant_id, home_currency_code=evidence_owner.home_currency_code,
        original_currency_code=evidence_owner.original_currency_code, source=source.source, category="其他", note="",
        image_path=saved.relative_path if saved else None, image_hash=saved.image_hash if saved else None,
        image_evidence=saved.image_evidence if saved else None,
        image_perceptual_hash=saved.image_perceptual_hash if saved else None,
        status="pending", created_at=now, updated_at=now)
    db.add(child)
    db.flush()
    return child


def independent_sibling_ids(db, expense, candidate_ids) -> set[int]:
    """Distinct cards in the same extraction are not duplicates, even at the same price."""
    rows = list(db.scalars(select(ExpenseSourceCandidate).where(
        ExpenseSourceCandidate.tenant_id == expense.tenant_id,
        ExpenseSourceCandidate.expense_id.in_({expense.id, *candidate_ids}))))
    own = next((row for row in rows if row.expense_id == expense.id), None)
    if own is None:
        return set()
    return {row.expense_id for row in rows if row.source_expense_id == own.source_expense_id
        and row.extraction_hash == own.extraction_hash and row.event_key != own.event_key}

"""Freeze notification time evidence once; every consumer uses the shared parser."""

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PaymentCapture
from app.schemas._recognition_time import RecognitionTimeResponse
from app.schemas.notification_time import NotificationTimeEvidence
from app.services.receipt_parse_candidates import resolve_field
from app.services.receipt_parse_common import FIELD_PARSE_VERSION
from app.services.receipt_parse_time import _time_candidates
from app.services.recognition_time_service import project_time_evidence


def freeze_notification_time(evidence: NotificationTimeEvidence | None, captured_at) -> dict | None:
    if evidence is None:
        return None
    raw = "\n".join(f"{item.label}：{item.literal}" if item.label else item.literal for item in evidence.fragments)
    candidates = _time_candidates(raw, timezone_name=evidence.source_timezone or "Etc/Unknown",
        reference_time=captured_at)
    _, public, decision = resolve_field(raw, "expense_time", candidates)
    values = [asdict(item) for item in public]
    for item in values:
        if item["timezone_basis"] == "source_timezone":
            item["timezone_basis"] = "capture_timezone"
    return {"schema": "notification-time/v1", "input": evidence.model_dump(), "raw_text": raw,
        "field_parse": {"version": FIELD_PARSE_VERSION, "reference_time": captured_at.isoformat(),
            "candidates": values, "decisions": [asdict(decision)]}}


def notification_time(capture: PaymentCapture) -> RecognitionTimeResponse | None:
    frozen = capture.time_evidence
    if not frozen:
        return None
    result = project_time_evidence(capture.public_id, "notification", frozen["field_parse"], frozen["raw_text"])
    if frozen["input"]["truncated"]:
        result = result or RecognitionTimeResponse(evidence_public_id=capture.public_id, source="notification",
            parser_version=frozen["field_parse"]["version"], status="incomplete", candidates=[])
        result.status = "incomplete"
    return result


def notification_times_for_expenses(db: Session, *, tenant_id: str, actor_account_id: int | None,
        expense_public_ids: list[str]) -> dict[str, RecognitionTimeResponse]:
    if actor_account_id is None or not expense_public_ids:
        return {}
    rows = db.scalars(select(PaymentCapture).where(PaymentCapture.tenant_id == tenant_id,
        PaymentCapture.actor_account_id == actor_account_id, PaymentCapture.expense_public_id.in_(expense_public_ids)))
    return {row.expense_public_id: evidence for row in rows if (evidence := notification_time(row)) is not None}


def notification_time_for_repayment(db: Session, *, tenant_id: str, actor_account_id: int,
        repayment_public_id: str) -> RecognitionTimeResponse | None:
    return notification_times_for_repayments(db, tenant_id=tenant_id, actor_account_id=actor_account_id,
        repayment_public_ids=[repayment_public_id]).get(repayment_public_id)


def notification_times_for_repayments(db: Session, *, tenant_id: str, actor_account_id: int,
        repayment_public_ids: list[str]) -> dict[str, RecognitionTimeResponse]:
    if not repayment_public_ids:
        return {}
    rows = db.scalars(select(PaymentCapture).where(PaymentCapture.tenant_id == tenant_id,
        PaymentCapture.actor_account_id == actor_account_id, PaymentCapture.repayment_public_id.in_(repayment_public_ids)))
    return {row.repayment_public_id: evidence for row in rows if (evidence := notification_time(row)) is not None}

"""Immutable notification fragments use the same field parser and personal proof."""
import hashlib
import json
from dataclasses import asdict, dataclass

from sqlalchemy import select

from app.models import Expense, PaymentCapture
from app.services.currency_common import minor_unit_digits
from app.services.receipt_parse_common import FIELD_PARSE_VERSION
from app.services.receipt_parse_service import parse_receipt_text
from app.services.recognition_evidence_context import capture_evidence_context, time_case_key


def freeze_notification_fields(evidence, currency) -> dict | None:
    if evidence is None:
        return None
    raw = "\n".join(item.literal for item in evidence.fragments)
    parsed = parse_receipt_text(raw, timezone_name="Etc/Unknown", currency_code=currency,
        minor_unit_exponent=minor_unit_digits(currency))
    return {"schema": "notification-fields/v1", "input": evidence.model_dump(), "raw_text": raw,
        "field_parse": {"version": FIELD_PARSE_VERSION,
            "candidates": [asdict(item) for item in parsed.candidates if item.field in {"amount_cents", "merchant"}],
            "events": list(parsed.events)}}


@dataclass(frozen=True)
class NotificationFieldSource:
    public_id: str
    raw_text: str
    evidence_json: str
    capture_context: dict
    case_key: str
    source: str = "notification"


def _field_source(capture):
    frozen = capture.field_evidence
    source = NotificationFieldSource(capture.public_id, frozen["raw_text"], json.dumps(frozen),
        capture_evidence_context(capture, kind="field"), "")
    # Neither another application nor another phone parser/currency inherits a case.
    key = json.dumps(["notification", capture.source, capture.parser_version, capture.original_currency,
        [item["field"] for item in frozen["input"]["fragments"]], frozen["input"]["truncated"], time_case_key(source)])
    return NotificationFieldSource(source.public_id, source.raw_text, source.evidence_json,
        source.capture_context, hashlib.sha256(key.encode()).hexdigest())


def notification_field_sources(db, *, tenant_id, actor_account_id, expense_ids):
    if actor_account_id is None or not expense_ids:
        return {}
    rows = db.execute(select(Expense.id, PaymentCapture).join(PaymentCapture,
        PaymentCapture.expense_public_id == Expense.public_id).where(Expense.tenant_id == tenant_id,
        Expense.id.in_(expense_ids), PaymentCapture.tenant_id == tenant_id,
        PaymentCapture.actor_account_id == actor_account_id, PaymentCapture.kind == "expense"))
    return {expense_id: _field_source(capture) for expense_id, capture in rows if capture.field_evidence}


def field_case_key(source):
    return getattr(source, "case_key", None) or time_case_key(source)

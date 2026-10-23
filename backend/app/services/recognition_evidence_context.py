"""Source fingerprints and case keys independent of feedback qualification or ranking."""
import hashlib
import json
import re
from typing import Literal

from sqlalchemy import select

from app.models import OcrFact, PaymentCapture


def capture_evidence_context(capture: PaymentCapture, *, kind: Literal["field", "time"]) -> dict:
    return {"public_id": capture.public_id, "row_version": capture.row_version, "kind": capture.kind,
        "expense_public_id": capture.expense_public_id, "actor_account_id": capture.actor_account_id,
        "parser_version": capture.parser_version,
        "evidence_sha256": hashlib.sha256(json.dumps(getattr(capture, kind + "_evidence"), sort_keys=True).encode()).hexdigest()}


def notification_evidence_contexts(db, *, tenant_id, payloads) -> tuple[dict, dict]:
    identifiers = {data.get("evidence_public_id") for data in payloads if data.get("source") == "notification"}
    rows = list(db.scalars(select(PaymentCapture).where(PaymentCapture.tenant_id == tenant_id,
        PaymentCapture.public_id.in_(identifiers)))) if identifiers else []
    return ({row.public_id: capture_evidence_context(row, kind="field") for row in rows},
        {row.public_id: capture_evidence_context(row, kind="time") for row in rows})


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

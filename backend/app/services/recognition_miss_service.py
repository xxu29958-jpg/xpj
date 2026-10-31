"""Observe unmatched saved readings without promoting bookkeeping into labels."""

import json
import re
import unicodedata
from decimal import Decimal

from app.fx_constants import CURRENCY_MINOR_UNIT_DIGITS
from app.services.learning_service import EventDraft, read_ocr_facts, record_event
from app.services.learning_service._algorithm_registry import RECOGNITION_FIELD_CHOICE, RECOGNITION_TIME_CHOICE
from app.services.recognition_time_values import candidate_components, time_components


def saved_readings(expense) -> dict:
    code = expense.original_currency_code or expense.home_currency_code
    minor = expense.original_amount_minor if expense.original_currency_code else expense.amount_cents
    return {"merchant": expense.merchant, "expense_time": time_components(expense),
        "amount_cents": {"value": minor, "currency_code": code,
                         "minor_unit_exponent": CURRENCY_MINOR_UNIT_DIGITS.get(code)}}


def _reading(fact, item):
    if item["field"] == "amount_cents":
        return {key: item.get(key) for key in ("value", "currency_code", "minor_unit_exponent")}
    if item["field"] == "expense_time":
        from app.services.recognition_time_service import _candidate

        candidate = _candidate(item, fact.raw_text or "", public_id=fact.public_id, source="image", version="miss")
        return candidate_components(candidate)
    return item["value"]


def _text_present(text: str, field: str, final) -> bool | None:
    text = unicodedata.normalize("NFKC", text).casefold()
    if field == "merchant":
        return unicodedata.normalize("NFKC", final).casefold() in text
    if field == "amount_cents":
        exponent = final["minor_unit_exponent"]
        if final["value"] is None or exponent is None:
            return None
        return any(Decimal(token.replace(",", "")) * (10 ** exponent) == final["value"]
            for token in re.findall(r"(?<![\d.,])-?\d[\d,]*(?:\.\d+)?(?![\d.])", text))
    # Missing year/timezone is not completed from the clock. This is literal
    # text presence only, not region verification or transaction attribution.
    if not all(key in final for key in ("year", "month", "day")):
        return None
    date = rf"(?<!\d){final['year']}[-/.年]\s*0?{final['month']}[-/.月]\s*0?{final['day']}(?!\d)"
    if not re.search(date, text):
        return False
    if final["precision"] == "date_only":
        return True
    clock = rf"(?<!\d)0?{final['hour']}[:时]\s*0?{final['minute']}(?!\d)"
    seconds = final.get("second", 0)
    clock += rf"[:分]\s*0?{seconds}(?!\d)" if seconds else r"(?!(?:[:分]\s*)0*[1-9]\d*)"
    return bool(re.search(clock, text))


def miss_metadata(fact, field: str, final, intent: str) -> dict | None:
    if final in (None, "", {}):
        return None
    candidates = json.loads(fact.evidence_json or "{}").get("field_parse", {}).get("candidates", [])
    if any(_reading(fact, item) == final for item in candidates if item["field"] == field):
        return None
    return {"kind": "reading" if intent == "original_correction" else "diagnostic",
        "text_present": _text_present(fact.raw_text or "", field, final)}


def record_unmatched_saves(db, *, expense, before: dict, actor_account_id, recorded_fields: set[str]) -> None:
    if actor_account_id is None:
        return
    current = saved_readings(expense)
    changed = [field for field, value in current.items() if value != before[field] and field not in recorded_fields]
    if not changed:
        return
    fact = read_ocr_facts(db, tenant_id=expense.tenant_id, expenses=[expense]).get(expense.id)
    if fact is None:
        return
    version = json.loads(fact.evidence_json or "{}").get("field_parse", {}).get("version")
    for field in changed:
        final = current[field]
        miss = miss_metadata(fact, field, final, "bookkeeping")
        if miss is None:
            continue
        definition = RECOGNITION_TIME_CHOICE if field == "expense_time" else RECOGNITION_FIELD_CHOICE
        values = ({"final_components": final} if field == "expense_time" else
            {"final_value": final["value"], "money_context": final} if field == "amount_cents" else {"final_value": final})
        payload = {**values, "field": field, "intent": "bookkeeping", "source": "image",
            "evidence_public_id": fact.public_id, "parser_version": version, "_candidate_miss": miss,
            "_learning_qualified": False, "_learning_target": "candidate_miss",
            "_algorithm_version": definition.current_version, "_action_outcome": "committed"}
        record_event(db, EventDraft(tenant_id=expense.tenant_id, subject_kind="expense", subject_id=expense.id,
            actor_account_id=actor_account_id, event_type="edit", signal_type=definition.decision_type,
            after_payload=payload, signal_marker={"field": field, "evidence_public_id": fact.public_id}))

"""Amount-role cases tolerate changed items while retaining the material context."""
import hashlib
import json
import re
import unicodedata

_ROLES = {"payment", "expense", "total", "final_total", "rounded_total", "unknown"}


def _normalized(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text).strip())


def _has_label(text, currency):
    return bool(re.sub(rf"\b(?:{currency.casefold()}|rm|rmb)\b|[#\s.,:+\-()$¥€£]+", "", _normalized(text)))


def _pattern(raw, lines, candidate):
    indices = sorted({raw.count("\n", 0, start) for start, _ in candidate["raw_spans"]}
        | {raw.count("\n", 0, max(start, end - 1)) for start, end in candidate["raw_spans"]})
    if not indices or indices[-1] - indices[0] > 1:
        return None
    text = " ".join(lines[index] for index in indices)
    currency = candidate["currency_code"]
    if not _has_label(text, currency) and indices[0] > 0:
        previous = lines[indices[0] - 1].strip()
        if len(previous) <= 60 and not re.search(r"\d", previous):
            text = previous + " " + text
    if not _has_label(text, currency):
        return None
    return [_normalized(text), candidate["role"], candidate["source"]]


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _amount_material(fact):
    if fact is None or getattr(fact, "source", "image") != "image":
        return None
    evidence = json.loads(fact.evidence_json or "{}").get("field_parse", {})
    candidates = [item for item in evidence.get("candidates", []) if item["field"] == "amount_cents" and item.get("currency_code")]
    currencies = {item["currency_code"] for item in candidates}
    if len(currencies) != 1 or len(evidence.get("events", [])) > 1:
        return None
    lines = fact.raw_text.splitlines()
    if len(lines) < 3:
        return None
    return evidence, candidates, currencies, lines


def amount_case_contexts(fact):
    """Return only comparable single-currency image cases; never infer a value."""
    material = _amount_material(fact)
    if material is None:
        return {}
    evidence, candidates, currencies, lines = material
    patterns = {item["id"]: pattern for item in candidates if (pattern := _pattern(fact.raw_text, lines, item)) is not None}
    # A new fee, changed field roles or another header never inherits the case.
    shape = sorted({_digest(pattern) for pattern in patterns.values()})
    scope = _digest([[_normalized(line) for line in lines[:3]], sorted(currencies), evidence.get("version"), shape])
    eligible = {item["id"] for item in candidates if item.get("role") in _ROLES}
    return {identifier: {"scope": scope, "choice": _digest(pattern)} for identifier, pattern in patterns.items() if identifier in eligible}

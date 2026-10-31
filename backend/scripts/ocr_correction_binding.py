"""Bind qualified image labels to parser candidates without relying on their IDs."""

import json
from dataclasses import asdict
from datetime import datetime

from app.fx_constants import CURRENCY_MINOR_UNIT_DIGITS
from app.services.recognition_source_service import candidate_source_location


def frozen_context(field_parse: dict) -> dict | None:
    candidates = field_parse.get("candidates", [])
    zones = {item.get("timezone_name") for item in candidates
             if item.get("timezone_basis") in {"configured_timezone", "source_timezone"}}
    explicit = field_parse.get("input_context")
    if isinstance(explicit, dict):
        context = {key: explicit.get(key) for key in (
            "currency_code", "minor_unit_exponent", "timezone_name", "reference_time")}
    else:
        # Older facts froze these inputs on their candidates. Never borrow the
        # current Expense's money, current settings, or the current wall clock.
        money = {(item.get("currency_code"), item.get("minor_unit_exponent")) for item in candidates
                 if item.get("field") == "amount_cents" and item.get("currency_code") is not None}
        if len(money) != 1 or len(zones) > 1:
            return None
        code, exponent = money.pop()
        context = {"currency_code": code, "minor_unit_exponent": exponent,
                   "timezone_name": next(iter(zones), None), "reference_time": field_parse.get("reference_time")}
    if not context["timezone_name"]:
        context["timezone_name"] = next(iter(zones), None) if len(zones) == 1 else None
    return _validated_context(context)


def _validated_context(context: dict) -> dict | None:
    if not isinstance(context["timezone_name"], str) or not context["timezone_name"].strip():
        return None
    code, exponent = context["currency_code"], context["minor_unit_exponent"]
    if code is None:
        if exponent is not None:
            return None
    elif code not in CURRENCY_MINOR_UNIT_DIGITS or exponent != CURRENCY_MINOR_UNIT_DIGITS[code]:
        return None
    if context["reference_time"] is not None:
        try:
            context["reference_time"] = datetime.fromisoformat(context["reference_time"])
        except (TypeError, ValueError):
            return None
        if context["reference_time"].tzinfo is None:
            return None
    return context


def _rectangle(box):
    xs, ys = zip(*box, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _iou(left, right):
    a, b = _rectangle(left), _rectangle(right)
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / union if union else 0


def _same_value(item: dict, label: dict) -> bool:
    if item.get("field") != label["field"]:
        return False
    if label["field"] == "expense_time":
        # Compare the human-confirmed components, not a made-up midnight or year.
        from app.services.recognition_choice_service import _candidate_components
        from app.services.recognition_time_service import _candidate

        projected = _candidate_components(_candidate(item, "", public_id="replay", source="image", version="replay"))
        return bool(projected) and projected == label.get("final_components")
    if item.get("value") != label.get("final_value"):
        return False
    return label["field"] != "amount_cents" or (
        item.get("currency_code"), item.get("minor_unit_exponent")) == (
        label["selected"].get("currency_code"), label["selected"].get("minor_unit_exponent"))


def _bindings(fact, candidates, label, location):
    matches = []
    for item in candidates:
        if not _same_value(item, label):
            continue
        source = candidate_source_location(fact, item)
        if source is None or any(getattr(source, key) != getattr(location, key)
                for key in ("image_sha256", "width", "height", "coordinate_space")):
            continue
        # Every label box must rebind; an equal value somewhere else is not proof.
        if all(any(_iou(old, new) >= .5 for new in source.boxes) for old in location.boxes):
            matches.append(item)
    return matches


def replay_label(fact, label, parser) -> dict:
    from app.schemas._recognition_source import RecognitionSourceLocation

    evidence = json.loads(fact.evidence_json or "{}")
    old = evidence.get("field_parse", {})
    context = frozen_context(old)
    if context is None:
        return {"outcome": "unbindable", "reason": "missing_frozen_context"}
    selected = label.get("selected") or {}
    location_data = selected.get("source_location")
    if not location_data:
        return {"outcome": "unbindable", "reason": "missing_label_location"}
    location = RecognitionSourceLocation.model_validate(location_data)
    if location.image_sha256 != evidence.get("input_sha256"):
        return {"outcome": "unbindable", "reason": "source_identity_mismatch"}
    parsed = parser(fact.raw_text or "", evidence_blocks=evidence.get("blocks"), **context)
    baseline = _bindings(fact, old.get("candidates", []), label, location)
    current = _bindings(fact, [asdict(item) for item in parsed.candidates], label, location)
    return _binding_comparison(baseline, current, old, parsed)


def _binding_comparison(baseline: list, current: list, old: dict, parsed) -> dict:
    outcome = "same" if bool(baseline) == bool(current) else "fixed" if current else "broken"
    old_selected = {item.get("selected_id") for item in old.get("decisions", []) if item.get("status") == "selected"}
    new_selected = {item.selected_id for item in parsed.decisions if item.status == "selected"}
    return {"outcome": outcome, "reason": "bound" if current else "no_equal_value_at_label_region",
            "baseline_matches": len(baseline), "candidate_matches": len(current),
            "baseline_selected": any(item["id"] in old_selected or item.get("event_selected") for item in baseline),
            "candidate_selected": any(item["id"] in new_selected or item.get("event_selected") for item in current),
            "baseline_parser": old.get("version")}

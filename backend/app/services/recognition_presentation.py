"""Neutral source order for abstained image fields, with explicit wire provenance."""
import json


def _source_key(item, spans, image_order):
    start = min((span[0] for span in spans.get(item.id, [])), default=0)
    if image_order:
        points = [point for box in item.source_location.boxes for point in box]
        return min(point[1] for point in points), min(point[0] for point in points), start
    return start,


def _ordered_group(items, decision, spans):
    if decision.get("status") not in {"ambiguous", "needs_review"}:
        mode = "source-order-v1:ranked" if decision else None
        return [item.model_copy(update={"presentation": mode}) for item in items]
    image_order = all(item.source_location is not None for item in items)
    text_order = all(spans.get(item.id) for item in items)
    if not image_order and not text_order:
        return [item.model_copy(update={"presentation": None}) for item in items]
    mode = "source-order-v1:image" if image_order else "source-order-v1:text"
    return [item.model_copy(update={"presentation": mode}) for item in
        sorted(items, key=lambda item: _source_key(item, spans, image_order))]


def source_order(fact, candidates, *, field=None):
    """Keep field/source slots separate and event ids intact; ties preserve W3 alternatives."""
    result = list(candidates)
    if fact is None or not fact.evidence_json or getattr(fact, "source", "image") != "image":
        return result
    evidence = json.loads(fact.evidence_json).get("field_parse", {})
    decisions = {item["field"]: item for item in evidence.get("decisions", [])}
    spans = {item["id"]: item.get("raw_spans", []) for item in evidence.get("candidates", [])}
    groups = {}
    for index, item in enumerate(result):
        if item.source == "image" and item.evidence_public_id == fact.public_id:
            groups.setdefault(field or item.field, []).append(index)
    for name, indices in groups.items():
        ordered = _ordered_group([result[index] for index in indices], decisions.get(name, {}), spans)
        for index, item in zip(indices, ordered, strict=True):
            result[index] = item
    return result


def verified_presentation(choice, candidates):
    """Legacy or stale clients remain unknown, rather than inventing what they saw."""
    expected = next((item.presentation for item in candidates if item.id == choice.candidate_id), None)
    return choice.presentation if choice.presentation == expected else None

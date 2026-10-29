"""A candidate points to its own original blocks, not another equal value."""
import json
from types import SimpleNamespace

import pytest

from app.models import Expense
from app.services.ocr_service import OcrResult, ocr_fact_snapshot
from app.services.recognition_field_service import recognition_fields
from app.services.recognition_source_service import candidate_source_location
from app.services.recognition_time_service import recognition_time


def source_fact():
    lines = ["商户：盒马", "原价：49.90元", "实付：49.90元", "交易时间：2026-10-29 08:00:00"]
    blocks = [{"text": text, "confidence": .9, "box": [[10, i * 40], [390, i * 40],
        [390, i * 40 + 30], [10, i * 40 + 30]]} for i, text in enumerate(lines)]
    raw = "\n".join(lines)
    expense = Expense(home_currency_code="CNY", original_currency_code="CNY")
    snapshot = ocr_fact_snapshot(OcrResult(raw, .9, evidence={"width": 400, "height": 800,
        "input_sha256": "a" * 64, "coordinate_space": "exif-transposed-pixels", "blocks": blocks}),
        expense=expense, timezone_name="Asia/Shanghai")
    return SimpleNamespace(public_id="fact", raw_text=raw, evidence_json=json.dumps(snapshot.evidence))


def test_equal_amounts_keep_separate_source_blocks_and_time_has_its_own_location():
    fact = source_fact()
    amounts = [item for item in recognition_fields(fact) if item.field == "amount_cents"]
    price = next(item for item in amounts if item.role == "original_price")
    paid = next(item for item in amounts if item.role == "payment")
    assert price.value == paid.value == 4990
    assert price.source_location.boxes[0][0] == (10, 40)
    assert paid.source_location.boxes[0][0] == (10, 80)
    time = recognition_time(fact).candidates[0]
    assert time.source_location.boxes[0][0] == (10, 120)
    assert time.source_location.image_sha256 == "a" * 64


@pytest.mark.parametrize("change", ["no_blocks", "manual_text", "outside", "wrong_space", "wrong_index", "notification"])
def test_unreliable_location_does_not_invent_a_box(change):
    fact = source_fact()
    evidence = json.loads(fact.evidence_json)
    candidate = next(item for item in evidence["field_parse"]["candidates"] if item["field"] == "amount_cents")
    if change == "no_blocks":
        evidence.pop("blocks")
    elif change == "manual_text":
        fact.raw_text += "\n人工补充"
    elif change == "outside":
        evidence["width"] = 20
    elif change == "wrong_space":
        evidence["coordinate_space"] = "screen"
    elif change == "wrong_index":
        candidate["block_indices"] = [0]
    elif change == "notification":
        fact.source = "notification"
    fact.evidence_json = json.dumps(evidence)
    assert candidate_source_location(fact, candidate) is None

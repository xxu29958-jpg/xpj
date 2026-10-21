"""Business counterexamples for evaluation claims, independent of OCR availability."""

from __future__ import annotations

from scripts.ocr_benchmark_data import FIELDS, Label
from scripts.ocr_benchmark_metrics import ScoreRow, score, summarize


def labels(**values):
    return {name: values.get(name, Label("unlabeled")) for name in FIELDS}


def test_same_day_wrong_time_and_partial_merchant_are_errors():
    result = score({"merchant": "便利", "time": {"value": "2026-05-04T03:00:00+08:00", "precision": "instant"}},
                   labels(merchant=Label("present", "测试便利店"),
                          time=Label("present", {"value": "2026-05-04T12:00:00+08:00", "precision": "instant"})))
    assert result["merchant"] is False
    assert result["time"] is False


def test_same_instant_in_different_offsets_matches_but_date_only_does_not():
    actual = {"value": "2026-05-04T04:00:00Z", "precision": "instant"}
    target = labels(time=Label("present", {"value": "2026-05-04T12:00:00+08:00", "precision": "instant"}))
    assert score({"time": actual}, target)["time"] is True
    target["time"] = Label("present", {"value": "2026-05-04", "precision": "date_only", "timezone": "Asia/Shanghai"})
    assert score({"time": actual}, target)["time"] is False


def test_amount_requires_currency_and_merchant_normalization_does_not_merge_branches():
    target = labels(amount=Label("present", {"minor": 1200, "currency": "JPY"}),
                    merchant=Label("present", "Ｃａｆｅ  A"))
    assert score({"amount": {"minor": 1200, "currency": "CNY"}, "merchant": "cafe A"}, target) == {
        "amount": False, "merchant": True, "time": None, "category": None}
    assert score({"merchant": "Cafe A 分店"}, target)["merchant"] is False


def test_absent_unlabeled_errors_and_coverage_keep_distinct_denominators():
    cases = [
        (labels(merchant=Label("present", "店")), {"merchant": "店"}, "success"),
        (labels(merchant=Label("present", "店")), {}, "error"),
        (labels(merchant=Label("absent")), {"merchant": "编造商户"}, "success"),
        (labels(merchant=Label("absent")), {}, "success"),
        (labels(merchant=Label("absent")), {}, "error"),
        (labels(), {"merchant": "未标注"}, "success"),
    ]
    rows = [ScoreRow(str(index), str(index), "diagnostic", "diagnostic", "rapidocr", outcome,
                     60000 if outcome == "error" else 5, prediction,
                     score(prediction, truth, failed=outcome == "error"),
                     {name: label.state for name, label in truth.items()})
            for index, (truth, prediction, outcome) in enumerate(cases)]
    summary = summarize(rows)
    assert summary["attempted"] == 6
    assert summary["outcomes"] == {"success": 4, "error": 2}
    assert summary["latency_ms"]["all_p95"] == 60000
    assert summary["latency_ms"]["success_p95"] == 5
    assert summary["fields"]["merchant"] == {
        "labeled": 5, "unlabeled": 1, "correct": 2, "incorrect": 3,
        "expected_present": 2, "expected_absent": 3, "emitted_when_present": 1,
        "false_fill": 1, "accuracy": .4, "coverage": .5, "false_fill_rate": 1 / 3}

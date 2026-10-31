"""Synthetic stage fixtures prove diagnosis contracts, never image quality."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ocr_benchmark import benchmark
from scripts.ocr_benchmark_data import FIELDS, Label, discover_fixtures
from scripts.ocr_benchmark_stages import STAGES, analyze_fields, stage_summary, text_present


def labels():
    return {name: Label("present", {"minor": 1851, "currency": "CNY"}) if name == "amount"
            else Label("unlabeled") for name in FIELDS}


def amount(value, index=0):
    return {"id": str(index), "field": "amount_cents", "value": value, "currency_code": "CNY",
            "role": "paid", "rank_score": 90 - index, "block_indices": [index], "raw_spans": [[0, 5]]}


@pytest.mark.parametrize(("text", "candidates", "status", "prediction", "expected"), [
    ("商店", [], "missing", None, "text_missing"),
    ("18.51", [], "missing", None, "no_candidate"),
    ("18.51", [amount(2000), amount(1851, 1)], "selected", 2000, "not_first"),
    ("18.51", [amount(1851)], "needs_review", None, "first_abstained"),
    ("18.51", [amount(1851)], "selected", 1851, "correct"),
])
def test_each_stage_keeps_candidates_and_decision(text, candidates, status, prediction, expected):
    decision = {"field": "amount_cents", "status": status,
                "selected_id": "0" if status == "selected" else None, "reason": "fixture"}
    analysis = analyze_fields(text, {"candidates": candidates, "decisions": [decision]},
                              {"amount": {"minor": prediction, "currency": "CNY"} if prediction else None},
                              labels(), timezone_name="Asia/Shanghai")["amount"]
    assert analysis["stage"] == expected
    assert analysis["silent_error"] == (expected == "not_first")
    assert analysis["decision"] == decision
    for rank, candidate in enumerate(analysis["candidates"], 1):
        assert candidate["rank"] == rank
        assert candidate["block_indices"] == [rank - 1]


def test_wrong_selection_with_correct_top_is_not_counted_correct():
    analysis = analyze_fields("18.51", {"candidates": [amount(1851), amount(2000, 1)],
        "decisions": [{"field": "amount_cents", "status": "selected", "selected_id": "1"}]},
        {"amount": {"minor": 2000, "currency": "CNY"}}, labels(), timezone_name="UTC")["amount"]
    assert analysis["stage"] == "first_abstained"
    assert analysis["silent_error"] is True


def test_failed_extraction_and_absent_truth_stay_in_denominators():
    analysis = analyze_fields("", {}, {}, labels(), timezone_name="UTC", failed=True)
    rows = [SimpleNamespace(group_id="one", field_analysis=analysis)]
    report = stage_summary(rows)["amount"]
    assert report["present"] == sum(report["stages"].values()) == 1
    assert report["extraction_failures"] == 1
    assert report["stages"]["text_missing"] == 1
    analysis["amount"].update(label_state="absent", stage=None, silent_error=True)
    report = stage_summary(rows)["amount"]
    assert report["present"] == 0 and report["labeled"] == 1 and report["silent_errors"] == 1


def test_text_presence_does_not_use_parser_candidates_or_numeric_substrings():
    expected = labels()["amount"]
    assert text_present("amount", expected, "实付 ￥１８.５１", "UTC")
    assert not text_present("amount", expected, "118.51 1851 18.5101", "UTC")
    analysis = analyze_fields("118.51", {"candidates": [amount(1851)]}, {}, labels(), timezone_name="UTC")
    assert analysis["amount"]["stage"] == "text_missing"
    time = Label("present", {"value": "2026-05-04T08:23:25+00:00", "precision": "instant"})
    assert text_present("time", time, "2026年5月4日 16:23:25", "Asia/Shanghai")
    assert not text_present("time", time, "2026年5月4日 08:23:25", "Asia/Shanghai")


def test_bootstrap_samples_groups_with_all_their_images_together():
    def row(group, stage):
        return SimpleNamespace(group_id=group, field_analysis={"amount": {
            "label_state": "present", "stage": stage, "silent_error": False,
            "extraction_failed": False, "candidates": []}})
    report = stage_summary([row("same", stage) for stage in STAGES])["amount"]
    assert report["present"] == 5
    assert all(bounds == [.2, .2] for bounds in report["group_bootstrap_95"].values())


def test_development_selection_never_reads_holdout_labels_or_images(tmp_path):
    source = Path(__file__).resolve().parents[1] / "tests/_infra/ocr_fixtures/_synthetic_bank_alert"
    for split in ("development", "holdout"):
        folder = tmp_path / split
        shutil.copytree(source, folder)
        data = json.loads((folder / "input.json").read_text(encoding="utf-8"))
        data.update(sample_id=split, group_id=split, split=split, app_tag="bank")
        (folder / "input.json").write_text(json.dumps(data), encoding="utf-8")
        if split == "holdout":
            (folder / "ground_truth.json").write_text("sealed; cannot parse", encoding="utf-8")
            (folder / "image.png").write_bytes(b"sealed; digest deliberately unavailable")
    report = benchmark(tmp_path, ["mock"], split="development").to_dict()
    assert len(report["rows"]) == 1
    assert report["rows"][0]["fixture"] == "development"
    assert report["stage_analysis"]["mock"]["amount"]["stages"]["correct"] == 1
    assert report["app_stage_analysis"]["mock/bank"]["amount"]["present"] == 1
    assert discover_fixtures(tmp_path, split="development")[0].app_tag == "bank"

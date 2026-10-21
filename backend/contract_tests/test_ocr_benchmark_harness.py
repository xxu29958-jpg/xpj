"""Exercise the actual benchmark runner, provider boundary and frozen data rules."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ocr_benchmark  # noqa: E402
from ocr_benchmark_data import discover_fixtures  # noqa: E402

from app.services.ocr_service import OcrResult  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "_infra" / "ocr_fixtures"


def fixture_copy(tmp_path):
    fixture = tmp_path / "sample"
    shutil.copytree(FIXTURE_DIR / "_synthetic_bank_alert", fixture)
    return fixture


def change_json(path, **changes):
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_mock_parses_explicit_input_through_fact_path():
    report = ocr_benchmark.benchmark(FIXTURE_DIR, ["mock"])
    row = report.rows[0]
    assert row.outcome == "success", row.error
    assert row.scores["amount"] is True
    assert row.scores["merchant"] is True
    assert row.scores["time"] is True
    assert report.to_dict()["product_qualified"] is False
    assert report.manifest[0]["input_sha256"]
    assert report.manifest[0]["labels_sha256"]


def test_image_provider_failure_remains_in_every_labeled_denominator(tmp_path):
    report = ocr_benchmark.benchmark(FIXTURE_DIR, ["rapidocr"])
    assert report.failed
    assert report.rows[0].outcome == "error"
    assert report.rows[0].elapsed_ms >= 0
    assert all(value is False for value in report.rows[0].scores.values())
    summary = report.to_dict()["providers"]["rapidocr"]
    assert summary["attempted"] == 1
    assert summary["fields"]["amount"]["labeled"] == 1
    output = tmp_path / "failed.json"
    assert ocr_benchmark.main(["--fixture-dir", str(FIXTURE_DIR), "--providers", "rapidocr",
                               "--json-output", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["rows"][0]["outcome"] == "error"


@pytest.mark.parametrize("providers", ["", "unknown", "mock,mock"])
def test_bad_provider_selection_cannot_exit_success(providers):
    assert ocr_benchmark.main(["--providers", providers]) == 2


def test_empty_dataset_cannot_exit_success(tmp_path):
    assert ocr_benchmark.main(["--fixture-dir", str(tmp_path), "--providers", "mock"]) == 2


def test_ground_truth_currency_and_text_cannot_reach_provider(tmp_path, monkeypatch):
    fixture = fixture_copy(tmp_path)
    change_json(fixture / "input.json", currency_code=None)
    observed = []

    def provider(inputs):
        observed.append(inputs)
        return OcrResult(raw_text="交易金额：1200", confidence=None)

    monkeypatch.setitem(ocr_benchmark._PROVIDER_RUNNERS, "rapidocr", provider)
    first = ocr_benchmark.benchmark(tmp_path, ["rapidocr"]).rows[0]
    truth = json.loads((fixture / "ground_truth.json").read_text(encoding="utf-8"))
    truth["fields"]["amount"]["value"] = {"minor": 1200, "currency": "JPY"}
    truth["raw_text"] = "不得作为输入的答案"
    (fixture / "ground_truth.json").write_text(json.dumps(truth), encoding="utf-8")
    second = ocr_benchmark.benchmark(tmp_path, ["rapidocr"]).rows[0]
    assert first.prediction == second.prediction
    assert first.prediction["amount"] is None
    assert all(item.currency_code is None for item in observed)
    assert not hasattr(observed[0], "labels")


def test_rapidocr_uses_actual_provider_snapshot_and_keeps_source_bytes(tmp_path, monkeypatch):
    fixture = fixture_copy(tmp_path)
    image = fixture / "image.png"
    image.write_bytes(b"fake-image-only-for-boundary-test")
    change_json(fixture / "input.json", image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    snapshots = []

    def extract_snapshot(self, original, timezone_name=None):
        snapshots.append(original)
        assert original.path.read_bytes() == image.read_bytes()
        assert timezone_name == "Asia/Shanghai"
        return OcrResult(raw_text="中国建设银行\n交易金额：18.51（人民币）\n交易时间：2026年5月4日 16:23:25", confidence=None)

    monkeypatch.setattr(ocr_benchmark.RapidOcrProvider, "extract_snapshot", extract_snapshot)
    report = ocr_benchmark.benchmark(tmp_path, ["rapidocr"])
    assert report.rows[0].scores["amount"] is True
    assert report.rows[0].scores["time"] is True
    assert not snapshots[0].path.exists()
    assert image.read_bytes() == b"fake-image-only-for-boundary-test"


def test_changed_image_or_cross_split_event_cannot_be_evaluated(tmp_path):
    fixture = fixture_copy(tmp_path)
    image = fixture / "image.png"
    image.write_bytes(b"changed")
    change_json(fixture / "input.json", image_sha256="0" * 64)
    with pytest.raises(ValueError, match="digest"):
        discover_fixtures(tmp_path)
    change_json(fixture / "input.json", image_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    other = tmp_path / "variant"
    shutil.copytree(fixture, other)
    change_json(other / "input.json", sample_id="variant", split="holdout")
    with pytest.raises(ValueError, match="crosses splits"):
        discover_fixtures(tmp_path)


def test_manifest_and_tables_report_complete_denominators():
    report = ocr_benchmark.benchmark(FIXTURE_DIR, ["empty", "mock"])
    assert "Amount + currency" in report.to_markdown()
    assert "Attempted | Failed | Groups" in report.aggregate_per_provider()
    assert set(report.to_dict()["providers"]) == {"empty", "mock"}


def test_truth_only_dataset_is_not_an_ocr_input(tmp_path):
    fixture = fixture_copy(tmp_path)
    change_json(fixture / "input.json", raw_text=None)
    truth = json.loads((fixture / "ground_truth.json").read_text(encoding="utf-8"))
    truth["raw_text"] = "正确答案不可读入模型"
    (fixture / "ground_truth.json").write_text(json.dumps(truth), encoding="utf-8")
    report = ocr_benchmark.benchmark(tmp_path, ["mock"])
    assert report.failed
    assert report.rows[0].prediction == {}

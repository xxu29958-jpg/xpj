"""A replay must contain material, keep its source stable and serve its frozen original."""

import hashlib
import json
import subprocess

import pytest
from PIL import Image

from scripts import ocr_feedback_replay as replay_cli
from scripts.ocr_benchmark_data import FIELDS, BenchmarkInput, Fixture, Label
from scripts.ocr_feedback_replay_data import ReplayMaterial, load_replay
from scripts.ocr_feedback_replay_runtime import _seed


def test_empty_manifest_cannot_report_a_completed_evaluation(tmp_path):
    manifest = tmp_path / "empty.json"
    manifest.write_text(json.dumps({"schema_version": 1, "recordings": [], "arrival_order": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="at least one"):
        load_replay(manifest)


def test_replay_output_is_excluded_but_real_source_edits_remain_visible(tmp_path, monkeypatch):
    # A tiny independent Git fixture exercises native path filtering, without copying the application.
    root = tmp_path / "source"
    backend = root / "backend"
    (backend / "scripts").mkdir(parents=True)
    (backend / "tests").mkdir()
    source = backend / "scripts/ocr_feedback_replay_fixture.py"
    source.write_text("# original source\n", encoding="utf-8")
    (backend / "tests/test_ocr_feedback_replay.py").write_text("# replay test fixture\n", encoding="utf-8")
    for arguments in (("init",), ("add", "."),
            ("-c", "user.name=Replay Contract", "-c", "user.email=replay@example.invalid", "commit", "-m", "fixture")):
        subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)
    monkeypatch.setattr(replay_cli, "_BACKEND_ROOT", backend)
    output = backend / "replay-results"
    before = replay_cli.source_identity(output)
    output.mkdir()
    (output / "tests.log").write_text("generated evaluation output", encoding="utf-8")
    assert replay_cli.source_identity(output) == before
    unrelated = root / "outside-backend.py"
    unrelated.write_text("# an actual new source file\n", encoding="utf-8")
    assert replay_cli.source_identity(output) != before
    source.write_text("# changed replay source\n", encoding="utf-8")
    assert replay_cli.source_identity(output)["replay_sources"] != before["replay_sources"]


def test_frozen_replay_original_remains_readable_with_metadata(client, identity, tmp_path):
    image = tmp_path / "frozen.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 80), "white").save(image, format="JPEG", exif=exif)
    body = image.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    fixture = Fixture("metadata", "metadata", "synthetic", "diagnostic", "test-created",
        BenchmarkInput(image, None, "CNY", "Asia/Shanghai", digest),
        {field: Label("unlabeled") for field in FIELDS}, {"sample_id": "metadata"})
    snapshot = {"raw_text": "synthetic attachment", "parsed_amount_cents": None, "parsed_merchant": None,
        "parsed_category": None, "parse_confidence": None, "parsed_expense_time": None,
        "evidence": {"input_sha256": digest, "blocks": []}}
    expense_id, _ = _seed(ReplayMaterial(fixture, snapshot, "success"))
    response = client.get(f"/api/expenses/{expense_id}/image", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    assert response.content == body and response.headers["etag"] == f'"{digest}"'

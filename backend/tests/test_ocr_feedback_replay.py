"""Opt-in real-image replay; conftest owns PG and resets every comparison arm."""

import json
import os
from pathlib import Path

import pytest

from scripts.ocr_feedback_replay import MODES
from scripts.ocr_feedback_replay_data import load_replay
from scripts.ocr_feedback_replay_runtime import replay
from tests._runtime_protocol import negotiated_headers

pytestmark = [pytest.mark.real_db, pytest.mark.skipif(not os.environ.get("XPJ_OCR_REPLAY_MANIFEST"),
    reason="Run scripts/ocr_feedback_replay.py with an explicit frozen real-image manifest")]


@pytest.mark.parametrize("mode", MODES)
def test_production_feedback_replay(client, identity, mode):
    manifest = Path(os.environ["XPJ_OCR_REPLAY_MANIFEST"])
    output = Path(os.environ["XPJ_OCR_REPLAY_OUTPUT"]) / f"{mode}.json"
    materials = load_replay(manifest)
    report = replay(client, negotiated_headers(client, identity.app_headers), materials, mode)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    assert report["attempted"] == len(materials)
    assert all(row["outcome"] != "replay_error" for row in report["rows"]), "See retained per-arrival outcomes"
    holdout_events = sum(row.get("feedback", {}).get("events", 0) for row in report["rows"] if row["split"] == "holdout")
    assert holdout_events == 0
    if mode == "baseline":
        assert all(row.get("feedback", {}).get("events", 0) == 0 for row in report["rows"])

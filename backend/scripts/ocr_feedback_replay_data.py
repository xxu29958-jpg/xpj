"""Frozen real-image recordings and declared arrival order for feedback replay."""
import json
from dataclasses import dataclass
from pathlib import Path

from scripts.ocr_benchmark_data import Fixture, discover_fixtures, sha256


@dataclass(frozen=True)
class ReplayMaterial:
    fixture: Fixture
    snapshot: dict | None
    original_outcome: str


def _recording(entry: dict, root: Path) -> list[ReplayMaterial]:
    report_path, snapshots_path = root / entry["report"], root / entry["snapshots"]
    if sha256(report_path) != entry["report_sha256"] or sha256(snapshots_path) != entry["snapshots_sha256"]:
        raise ValueError("recording changed after replay manifest was frozen")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("source_unchanged") or not report.get("worker_closed"):
        raise ValueError("recording did not finish with a stable source and closed worker")
    fixtures = {item.name: item for item in discover_fixtures(root / entry["fixtures"])}
    snapshots = [json.loads(line) for line in snapshots_path.read_text(encoding="utf-8").splitlines()]
    by_hash = {item["evidence"]["input_sha256"]: item for item in snapshots}
    if len(by_hash) != len(snapshots):
        raise ValueError("duplicate recorded image snapshots")
    identities = {item["sample_id"]: item for item in report["manifest"]}
    result = []
    for row in report["rows"]:
        fixture = fixtures[row["fixture"]]
        if row["provider"] != "rapidocr" or fixture.inputs.image is None:
            raise ValueError("feedback replay requires a real native image recording")
        if identities[fixture.name] != fixture.identity:
            raise ValueError("image inputs or annotations changed after recording")
        snapshot = by_hash.get(fixture.inputs.image_sha256)
        if row["outcome"] == "success" and snapshot is None:
            raise ValueError("successful recording has no native snapshot")
        result.append(ReplayMaterial(fixture, snapshot, row["outcome"]))
    if len(result) != len(fixtures):
        raise ValueError("recording omitted inputs from its denominator")
    return result


def load_replay(path: Path) -> list[ReplayMaterial]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported feedback replay manifest")
    material = [item for entry in manifest["recordings"] for item in _recording(entry, path.parent)]
    indexed = {item.fixture.name: item for item in material}
    order = manifest["arrival_order"]
    if len(indexed) != len(material) or len(set(order)) != len(order) or set(order) != set(indexed):
        raise ValueError("arrival order must contain every input exactly once")
    ordered = [indexed[name] for name in order]
    groups, images = set(), set()
    holdout_started = False
    for item in ordered:
        fixture = item.fixture
        if fixture.group_id in groups or fixture.inputs.image_sha256 in images:
            raise ValueError("replay requires distinct transaction groups and images")
        if fixture.split not in {"development", "holdout"}:
            raise ValueError("diagnostics cannot be presented as independent image replay")
        if holdout_started and fixture.split != "holdout":
            raise ValueError("development feedback cannot follow the frozen holdout")
        holdout_started = holdout_started or fixture.split == "holdout"
        groups.add(fixture.group_id)
        images.add(fixture.inputs.image_sha256)
    return ordered

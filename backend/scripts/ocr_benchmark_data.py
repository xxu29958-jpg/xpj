"""Frozen evaluation inputs and labels; providers never receive labels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.fx_constants import CURRENCY_MINOR_UNIT_DIGITS

FIELDS = ("amount", "merchant", "time", "category")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class BenchmarkInput:
    image: Path | None
    raw_text: str | None
    currency_code: str | None
    timezone_name: str
    image_sha256: str | None = None


@dataclass(frozen=True)
class Label:
    state: str
    value: object = None


@dataclass(frozen=True)
class Fixture:
    name: str
    group_id: str
    source_kind: str
    split: str
    authorization: str
    inputs: BenchmarkInput
    labels: dict[str, Label]
    identity: dict[str, object]


def _validate_label(name: str, data: dict) -> Label:
    state, value = data.get("state"), data.get("value")
    if state not in {"present", "absent", "unlabeled"}:
        raise ValueError(f"{name}: state must be present, absent or unlabeled")
    if state != "present":
        if value is not None:
            raise ValueError(f"{name}: {state} cannot have a value")
        return Label(state)
    if name == "amount":
        if not isinstance(value, dict) or type(value.get("minor")) is not int:
            raise ValueError("amount requires integer minor units and currency")
        if not 0 < value["minor"] < 2**63:
            raise ValueError("amount minor units outside supported range")
        if value.get("currency") not in CURRENCY_MINOR_UNIT_DIGITS:
            raise ValueError("amount label requires a canonical supported currency")
    elif name == "time":
        _validate_time(value)
    elif not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: present requires nonempty text")
    return Label(state, value)


def _validate_time(value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError("time requires value and precision")
    if value.get("precision") == "date_only":
        date.fromisoformat(value["value"])
        ZoneInfo(value["timezone"])
    elif value.get("precision") == "instant":
        instant = datetime.fromisoformat(value["value"].replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("instant labels require an explicit UTC offset")
    else:
        raise ValueError("time precision must be instant or date_only")


def _read_fixture(entry: Path) -> Fixture:
    input_path, truth_path = entry / "input.json", entry / "ground_truth.json"
    data = json.loads(input_path.read_text(encoding="utf-8"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 2 or truth.get("schema_version") != 2:
        raise ValueError(f"{entry.name}: migrate input and ground truth to schema 2")
    for name in ("sample_id", "group_id", "source_kind", "authorization"):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise ValueError(f"{entry.name}: missing {name}")
    if data.get("split") not in {"diagnostic", "development", "holdout"}:
        raise ValueError(f"{entry.name}: invalid split")
    for name in ("annotator", "annotation_version"):
        if not isinstance(truth.get(name), str) or not truth[name].strip():
            raise ValueError(f"{entry.name}: missing {name}")
    timezone_name = data["timezone"]
    ZoneInfo(timezone_name)
    currency = data.get("currency_code")
    if currency is not None and currency not in CURRENCY_MINOR_UNIT_DIGITS:
        raise ValueError(f"{entry.name}: unsupported input currency")
    images = [entry / name for name in ("image.png", "image.jpg", "image.jpeg", "image.webp")
              if (entry / name).is_file()]
    if len(images) > 1:
        raise ValueError(f"{entry.name}: ambiguous image input")
    image = images[0] if images else None
    if image and data.get("image_sha256") != sha256(image):
        raise ValueError(f"{entry.name}: image digest missing or changed")
    raw_text = data.get("raw_text")
    if raw_text is not None and not isinstance(raw_text, str):
        raise ValueError(f"{entry.name}: raw_text must be a string")
    labels = {name: _validate_label(name, truth["fields"].get(name, {"state": "unlabeled"}))
              for name in FIELDS}
    identity = {name: data[name] for name in ("sample_id", "group_id", "source_kind", "split", "authorization")}
    identity.update(input_sha256=sha256(input_path), labels_sha256=sha256(truth_path),
                    image_sha256=sha256(image) if image else None,
                    annotator=truth["annotator"], annotation_version=truth["annotation_version"])
    return Fixture(data["sample_id"], data["group_id"], data["source_kind"], data["split"],
                   data["authorization"], BenchmarkInput(image, raw_text, currency, timezone_name,
                                                        data.get("image_sha256")), labels, identity)


def discover_fixtures(directory: Path) -> list[Fixture]:
    if not directory.is_dir():
        raise ValueError("fixture directory does not exist")
    fixtures = [_read_fixture(entry) for entry in sorted(directory.iterdir())
                if entry.is_dir() and (entry / "ground_truth.json").is_file()]
    if not fixtures:
        raise ValueError("no fixtures evaluated")
    names: set[str] = set()
    groups: dict[str, str] = {}
    image_groups: dict[str, str] = {}
    for fixture in fixtures:
        if fixture.name in names:
            raise ValueError(f"duplicate sample_id: {fixture.name}")
        names.add(fixture.name)
        if groups.setdefault(fixture.group_id, fixture.split) != fixture.split:
            raise ValueError(f"event group crosses splits: {fixture.group_id}")
        digest = fixture.inputs.image_sha256
        if digest and image_groups.setdefault(digest, fixture.group_id) != fixture.group_id:
            raise ValueError("identical images cannot be declared independent event groups")
    if not any(label.state != "unlabeled" for fixture in fixtures for label in fixture.labels.values()):
        raise ValueError("dataset contains no labeled fields")
    return fixtures

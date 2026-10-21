"""Exact field scoring with complete failure, annotation and coverage denominators."""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime

from ocr_benchmark_data import FIELDS, Label


def _merchant(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def score(prediction: dict, labels: dict[str, Label], *, failed: bool = False) -> dict[str, bool | None]:
    result = {}
    for name in FIELDS:
        label, actual = labels[name], prediction.get(name)
        if label.state == "unlabeled":
            result[name] = None
        elif failed:
            result[name] = False
        elif label.state == "absent":
            result[name] = actual is None
        elif actual is None:
            result[name] = False
        elif name == "merchant":
            result[name] = _merchant(actual) == _merchant(label.value)
        elif name == "time":
            result[name] = _time_match(actual, label.value)
        else:
            result[name] = actual == label.value
    return result


def _time_match(actual: dict, expected: dict) -> bool:
    if actual.get("precision") != expected["precision"]:
        return False
    if expected["precision"] == "date_only":
        return actual == expected
    parsed = datetime.fromisoformat(actual["value"].replace("Z", "+00:00"))
    target = datetime.fromisoformat(expected["value"].replace("Z", "+00:00"))
    return parsed.tzinfo is not None and parsed == target


@dataclass
class ScoreRow:
    fixture: str
    group_id: str
    source_kind: str
    split: str
    provider: str
    outcome: str
    elapsed_ms: float
    prediction: dict
    scores: dict[str, bool | None]
    labels: dict[str, str]
    error: str | None = None


def _percentile(values: list[float], percentile: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * percentile) - 1)] if values else None


def _field_counts(rows: list[ScoreRow], name: str) -> dict:
    labeled = [row for row in rows if row.labels[name] != "unlabeled"]
    present = [row for row in rows if row.labels[name] == "present"]
    absent = [row for row in rows if row.labels[name] == "absent"]
    correct = sum(row.scores[name] is True for row in labeled)
    emitted = sum(row.prediction.get(name) is not None for row in present)
    false_fill = sum(row.prediction.get(name) is not None for row in absent)
    return {"labeled": len(labeled), "unlabeled": len(rows) - len(labeled), "correct": correct,
            "incorrect": len(labeled) - correct, "expected_present": len(present), "expected_absent": len(absent),
            "emitted_when_present": emitted, "false_fill": false_fill,
            "accuracy": correct / len(labeled) if labeled else None,
            "coverage": emitted / len(present) if present else None,
            "false_fill_rate": false_fill / len(absent) if absent else None}


def summarize(rows: list[ScoreRow]) -> dict:
    durations = [row.elapsed_ms for row in rows]
    successful = [row.elapsed_ms for row in rows if row.outcome == "success"]
    return {"attempted": len(rows), "outcomes": dict(Counter(row.outcome for row in rows)),
            "independent_groups": len({row.group_id for row in rows}),
            "latency_ms": {"all_p50": _percentile(durations, .5), "all_p95": _percentile(durations, .95),
                           "success_p50": _percentile(successful, .5), "success_p95": _percentile(successful, .95)},
            "fields": {name: _field_counts(rows, name) for name in FIELDS}}


@dataclass
class BenchmarkReport:
    manifest: list[dict]
    rows: list[ScoreRow] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return not self.rows or any(row.outcome != "success" for row in self.rows)

    def to_dict(self) -> dict:
        providers = sorted({row.provider for row in self.rows})
        summaries = {provider: summarize([row for row in self.rows if row.provider == provider]) for provider in providers}
        slices = {}
        for provider in providers:
            for dimension in ("source_kind", "split"):
                values = {getattr(row, dimension) for row in self.rows if row.provider == provider}
                for value in sorted(values):
                    slices[f"{provider}/{dimension}/{value}"] = summarize([
                        row for row in self.rows if row.provider == provider and getattr(row, dimension) == value])
        return {"schema_version": 2, "evaluation_completed": not self.failed, "product_qualified": False,
                "manifest": self.manifest, "providers": summaries, "slices": slices,
                "rows": [asdict(row) for row in self.rows]}

    def to_markdown(self) -> str:
        lines = ["| Fixture | Provider | Outcome | Amount + currency | Merchant | Time + precision | Category | ms |",
                 "|---|---|---|---|---|---|---|---:|"]
        for row in self.rows:
            cells = ["—" if row.scores[name] is None else ("✓" if row.scores[name] else "✗") for name in FIELDS]
            lines.append(f"| {row.fixture} | {row.provider} | {row.outcome} | " + " | ".join(cells) + f" | {row.elapsed_ms:.2f} |")
        lines.append("\n完成运行不等于产品验收；合成样本、解析层探针和重复调用不构成独立真实事件。")
        return "\n".join(lines) + "\n"

    def aggregate_per_provider(self) -> str:
        lines = ["| Provider | Attempted | Failed | Groups | Field | Correct / labeled | Coverage present | False fill / absent |",
                 "|---|---:|---:|---:|---|---|---|---|"]
        for provider, summary in self.to_dict()["providers"].items():
            failures = summary["attempted"] - summary["outcomes"].get("success", 0)
            for name, counts in summary["fields"].items():
                lines.append(f"| {provider} | {summary['attempted']} | {failures} | {summary['independent_groups']} | {name} | "
                             f"{counts['correct']} / {counts['labeled']} | {counts['emitted_when_present']} / {counts['expected_present']} | "
                             f"{counts['false_fill']} / {counts['expected_absent']} |")
        return "\n".join(lines) + "\n"

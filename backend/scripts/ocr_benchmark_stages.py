"""Stage diagnosis for frozen OCR observations; labels never reach the parser.

Text presence is an independent literal check, not a claim about OCR quality.
An optional annotated source_text disambiguates source formatting. Missing and
absent annotations, extraction failures and silent selections remain explicit.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.fx_constants import CURRENCY_MINOR_UNIT_DIGITS
from scripts.ocr_benchmark_data import Label
from scripts.ocr_benchmark_metrics import _score_field

FIELD_NAMES = {"amount": "amount_cents", "merchant": "merchant", "time": "expense_time"}
STAGES = ("text_missing", "no_candidate", "not_first", "first_abstained", "correct")


def _text(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def text_present(field: str, label: Label, raw_text: str, timezone_name: str) -> bool:
    if label.source_text is not None:
        literal = _text(label.source_text)
        prefix = r"(?<![\d.,])" if field in {"amount", "time"} and literal[0].isdecimal() else ""
        suffix = r"(?![\d.,])" if field in {"amount", "time"} and literal[-1].isdecimal() else ""
        return bool(re.search(prefix + re.escape(literal) + suffix, _text(raw_text)))
    if field == "merchant":
        return _text(str(label.value)) in _text(raw_text)
    if field == "amount":
        value = label.value
        expected = Decimal(value["minor"]).scaleb(-CURRENCY_MINOR_UNIT_DIGITS[value["currency"]])
        normalized = unicodedata.normalize("NFKC", raw_text)
        tokens = re.findall(r"(?<![\d.])[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?![\d.])", normalized)
        return any(abs(Decimal(token.replace(",", ""))) == expected for token in tokens)
    return _time_text_present(label.value, raw_text, timezone_name)


def _printed_offsets(raw_text: str):
    for match in re.finditer(r"Z|(?:UTC|GMT)?(?P<sign>[+-])(?P<hour>\d{1,2})(?::?(?P<minute>\d{2}))?(?![\d:])",
                            raw_text, re.I):
        if match[0].upper() == "Z":
            yield match[0], UTC
            continue
        minutes = int(match["minute"] or 0)
        if minutes >= 60:
            continue
        delta = timedelta(hours=int(match["hour"]), minutes=minutes)
        try:
            zone = timezone(delta if match["sign"] == "+" else -delta)
        except ValueError:
            continue
        yield match[0], zone


def _time_patterns(local, instant):
    orders = [(local.year, local.month, local.day), (local.day, local.month, local.year),
              (local.month, local.day, local.year)]
    suffix = (local.hour, local.minute) if instant else ()
    for parts in orders:
        pattern = r"(?<!\d)" + r"\D+".join(f"0*{part}" for part in parts + suffix)
        if suffix:
            seconds = rf"\s*[:：分]\s*0*{local.second}"
            pattern += f"(?:{seconds})?" if local.second == 0 else seconds
            pattern += r"(?!\d|\s*[:：]|\s*分\s*\d)"
        else:
            pattern += r"(?!\d)"
        yield pattern


def _time_text_present(value: dict, raw_text: str, timezone_name: str) -> bool:
    raw_text = unicodedata.normalize("NFKC", raw_text)
    local = datetime.fromisoformat(value["value"].replace("Z", "+00:00"))
    instant = value["precision"] == "instant"
    if instant:
        for printed, zone in _printed_offsets(raw_text):
            for pattern in _time_patterns(local.astimezone(zone), True):
                if re.search(pattern + r"(?:秒|分)?\s*" + re.escape(printed) + r"(?![\d:])", raw_text, re.I):
                    return True
        local = local.astimezone(ZoneInfo(timezone_name))
    for pattern in _time_patterns(local, instant):
        if instant:
            pattern += r"(?!(?:秒|分)?\s*(?:Z|(?:UTC|GMT)?[+-]\d))"
        if re.search(pattern, raw_text, re.I):
            return True
    return False


def candidate_value(field: str, candidate: dict) -> object:
    value = candidate["value"]
    if field == "amount":
        return {"minor": value, "currency": candidate.get("currency_code")}
    if field == "time":
        try:
            instant = datetime.fromisoformat(str(candidate.get("local_value") or value))
        except ValueError:
            return None  # Incomplete date/time is useful evidence, not an instant.
        if candidate.get("precision") == "date_only":
            return {"value": instant.date().isoformat(), "precision": "date_only",
                    "timezone": candidate.get("timezone_name")}
        try:
            if datetime.fromisoformat(str(value)).tzinfo is None:
                return None
        except ValueError:
            return None
        return {"value": value, "precision": "instant"}
    return value


def analyze_fields(raw_text: str, field_parse: dict, prediction: dict, labels: dict[str, Label], *,
                   timezone_name: str, failed: bool = False) -> dict:
    result = {}
    decisions = {item["field"]: item for item in field_parse.get("decisions", [])}
    for field, parser_name in FIELD_NAMES.items():
        label = labels[field]
        candidates = [dict(item, rank=index + 1) for index, item in enumerate(
            item for item in field_parse.get("candidates", []) if item["field"] == parser_name)]
        decision = decisions.get(parser_name, {"status": "missing", "selected_id": None, "reason": "no_observation"})
        correct = _score_field(field, prediction.get(field), label, failed)
        selected = decision["status"] == "selected"
        analysis = {"label_state": label.state, "candidates": candidates, "decision": decision,
                    "stage": None, "text_present": None, "correct_candidate_ranks": [],
                    "silent_error": prediction.get(field) is not None and correct is False, "extraction_failed": failed,
                    "source_region": label.source_region}
        if label.state == "present":
            ranks = [item["rank"] for item in candidates
                     if _score_field(field, candidate_value(field, item), label, False)]
            present = text_present(field, label, raw_text, timezone_name)
            stage = classify_stage(present, ranks, selected and correct is True)
            analysis.update(stage=stage, text_present=present,
                            correct_candidate_ranks=ranks)
        result[field] = analysis
    return result


def classify_stage(text_seen: bool, correct_ranks: list[int], selected_correct: bool) -> str:
    if not text_seen:
        return "text_missing"
    if not correct_ranks:
        return "no_candidate"
    if 1 not in correct_ranks:
        return "not_first"
    return "correct" if selected_correct else "first_abstained"


def stage_summary(rows: list, *, bootstrap_samples: int = 1000) -> dict:
    """Percentile bootstrap resamples entire transaction groups, never image rows."""
    result = {}
    for field in FIELD_NAMES:
        observations = [(row.group_id, row.field_analysis[field]) for row in rows if field in row.field_analysis]
        present = [(group, item) for group, item in observations if item["label_state"] == "present"]
        counts = Counter(item["stage"] for _, item in present)
        labeled = [item for _, item in observations if item["label_state"] != "unlabeled"]
        result[field] = {"present": len(present), "labeled": len(labeled),
                         "unlabeled": sum(item["label_state"] == "unlabeled" for _, item in observations),
                         "stages": {stage: counts[stage] for stage in STAGES},
                         "silent_errors": sum(item["silent_error"] for item in labeled),
                         "extraction_failures": sum(item["extraction_failed"] for item in labeled),
                         "candidates_total": sum(len(item["candidates"]) for _, item in observations),
                         "group_bootstrap_95": _intervals(present, bootstrap_samples)}
    return result


def _intervals(observations: list[tuple[str, dict]], repetitions: int) -> dict:
    groups = defaultdict(list)
    for group, item in observations:
        groups[group].append(item["stage"])
    if not groups:
        return dict.fromkeys(STAGES)
    values = list(groups.values())
    rng = random.Random(0)
    draws = {stage: [] for stage in STAGES}
    for _ in range(repetitions):
        sample = [stage for cluster in rng.choices(values, k=len(values)) for stage in cluster]
        counts = Counter(sample)
        for stage in STAGES:
            draws[stage].append(counts[stage] / len(sample))
    return {stage: [sorted(rates)[int(.025 * (repetitions - 1))],
                    sorted(rates)[int(.975 * (repetitions - 1))]] for stage, rates in draws.items()}

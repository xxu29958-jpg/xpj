from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.receipt_parse_rules import RELATIVE_TIME_PATTERNS, TIME_PATTERNS
from app.services.receipt_parse_service import (
    _ReceiptContext,
    _ScoreDimensions,
    _TimeCandidate,
    _best_candidate,
    _build_receipt_context,
    _line_index_for_offset,
    _merge_dimensions,
    _nearby_text,
)
from app.services.time_service import ensure_utc


def _extract_expense_time(
    text: str, timezone_name: str | None = None
) -> datetime | None:
    context = _build_receipt_context(text)
    candidate = _best_candidate(
        _calibrate_time_candidates(_time_candidates(text, timezone_name), context)
    )
    return candidate.value if candidate else None


def _time_candidates(
    text: str, timezone_name: str | None = None
) -> list[_TimeCandidate]:
    candidates: list[_TimeCandidate] = []
    for pattern_index, pattern in enumerate(TIME_PATTERNS):
        for match in pattern.finditer(text):
            year, month, day, hour, minute, second = match.groups()
            try:
                local_value = datetime(
                    int(year),
                    int(month),
                    int(day),
                    int(hour),
                    int(minute),
                    int(second or 0),
                    tzinfo=_default_timezone(timezone_name),
                )
            except ValueError:
                continue

            match_text = match.group(0)
            dimensions = _score_time_dimensions(match_text, pattern_index)
            candidates.append(
                _TimeCandidate(
                    value=ensure_utc(local_value),
                    score=dimensions.total,
                    line_index=_line_index_for_offset(text, match.start()),
                    source=f"time_pattern:{pattern_index}",
                    evidence=dimensions.evidence,
                    dimensions=dimensions,
                )
            )
    for pattern_index, pattern in enumerate(RELATIVE_TIME_PATTERNS):
        for match in pattern.finditer(text):
            month, day, hour, minute, second = match.groups()
            try:
                local_value = datetime(
                    _default_local_year(timezone_name),
                    int(month),
                    int(day),
                    int(hour),
                    int(minute),
                    int(second or 0),
                    tzinfo=_default_timezone(timezone_name),
                )
            except ValueError:
                continue

            match_text = match.group(0)
            dimensions = _score_relative_time_dimensions(
                text, match.start(), match_text, pattern_index
            )
            candidates.append(
                _TimeCandidate(
                    value=ensure_utc(local_value),
                    score=dimensions.total,
                    line_index=_line_index_for_offset(text, match.start()),
                    source=f"relative_time_pattern:{pattern_index}",
                    evidence=dimensions.evidence,
                    dimensions=dimensions,
                )
            )
    return candidates


def _score_time_match(match_text: str, pattern_index: int) -> int:
    return _score_time_dimensions(match_text, pattern_index).total


def _score_time_dimensions(match_text: str, pattern_index: int) -> _ScoreDimensions:
    evidence = [match_text]
    if any(
        label in match_text
        for label in ["交易时间", "支付时间", "付款时间", "消费时间"]
    ):
        return _ScoreDimensions(
            label=78, context=18, evidence=tuple(evidence + ["business_time"])
        )
    if any(label in match_text for label in ["下单时间", "订单时间"]):
        return _ScoreDimensions(
            label=62, context=12, evidence=tuple(evidence + ["order_time"])
        )
    if any(label in match_text for label in ["创建时间", "来电时间"]):
        return _ScoreDimensions(
            label=34, context=6, evidence=tuple(evidence + ["generic_event_time"])
        )
    if "时间" in match_text:
        return _ScoreDimensions(
            label=42, context=8, evidence=tuple(evidence + ["generic_time"])
        )
    return _ScoreDimensions(
        source=max(18, 38 - pattern_index * 4),
        evidence=tuple(evidence + ["plain_datetime"]),
    )


def _score_relative_time_dimensions(
    text: str, offset: int, match_text: str, pattern_index: int
) -> _ScoreDimensions:
    line_index = _line_index_for_offset(text, offset)
    lines = text.splitlines()
    nearby = _nearby_text(tuple(lines), line_index, before=1, after=1)
    evidence = [match_text, "relative_year_from_runtime"]
    if any(
        marker in nearby
        for marker in ["支出", "交易", "支付", "付款", "扣款", "动账提醒"]
    ):
        return _ScoreDimensions(
            source=44,
            context=28,
            structure=12,
            evidence=tuple(evidence + ["near_business_event"]),
        )
    return _ScoreDimensions(
        source=max(18, 28 - pattern_index * 4),
        evidence=tuple(evidence + ["plain_relative_datetime"]),
    )


def _calibrate_time_candidates(
    candidates: list[_TimeCandidate], context: _ReceiptContext
) -> list[_TimeCandidate]:
    calibrated: list[_TimeCandidate] = []
    for candidate in candidates:
        profile = 0
        noise = 0
        evidence: list[str] = []
        evidence_text = "\n".join(candidate.evidence)
        if context.profile in {"alipay_bill_detail", "bank_reminder"} and any(
            label in evidence_text for label in ["交易时间", "支付时间", "付款时间"]
        ):
            profile += 10
            evidence.append(f"profile_{context.profile}_business_time:+10")
        if context.profile == "bank_reminder" and candidate.source.startswith(
            "relative_time_pattern"
        ):
            profile += 24
            evidence.append("profile_bank_relative_business_time:+24")
        if context.profile != "mobility_payment" and any(
            label in evidence_text for label in ["创建时间", "来电时间"]
        ):
            noise -= 10
            evidence.append("non_business_time_noise:-10")

        if profile == 0 and noise == 0:
            calibrated.append(candidate)
            continue

        dimensions = _merge_dimensions(
            candidate.dimensions, profile=profile, noise=noise, evidence=tuple(evidence)
        )
        calibrated.append(
            _TimeCandidate(
                value=candidate.value,
                score=dimensions.total,
                line_index=candidate.line_index,
                source=candidate.source,
                evidence=dimensions.evidence,
                dimensions=dimensions,
            )
        )
    return calibrated


def _default_timezone(timezone_name: str | None = None) -> ZoneInfo:
    name = (timezone_name or "").strip() or get_settings().ocr_default_timezone
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def _default_local_year(timezone_name: str | None = None) -> int:
    return datetime.now(_default_timezone(timezone_name)).year

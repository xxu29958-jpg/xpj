"""Receipt time evidence: keep roles and precision before resolving an instant."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.receipt_parse_common import (
    _line_index_for_offset,
    _ScoreDimensions,
    _TimeCandidate,
)

_CLOCK = (
    r"(?:(?P<period>上午|下午|晚上)\s*)?(?P<hour>\d{1,2})[时:：](?P<minute>\d{2})"
    r"(?:(?:[:：]|分)(?P<second>\d{2})秒?|分)?"
    r"(?:\s*(?P<ampm>AM|PM))?"
    r"(?:\s*(?P<offset>Z|(?:UTC|GMT)?[+-][\d:]+))?(?!\d)"
)
_CLOCK_SUFFIX = rf"(?:[T\s]+(?:(?:时间|TIME)\s*[:：]?\s*)?{_CLOCK})?"
_PATTERNS = (
    ("ymd_zh", re.compile(r"(?<!\d)(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日" + rf"(?:\s*{_CLOCK})?", re.I)),
    ("ymd_compact", re.compile(r"(?<!\d)(?P<year>\d{4})[/.-](?P<month>\d{2})[/.-](?P<day>\d{2})" + _CLOCK, re.I)),
    ("ymd", re.compile(r"(?<!\d)(?P<year>\d{4})[年/.-](?P<month>\d{1,2})[月/.-](?P<day>\d{1,2})日?(?!\d)" + _CLOCK_SUFFIX, re.I)),
    ("day_month", re.compile(r"(?<![\d/.-])(?P<first>\d{1,2})[/.-](?P<last>\d{1,2})[/.-](?P<year>\d{4})(?!\d)" + _CLOCK_SUFFIX, re.I)),
    ("month_name", re.compile(r"(?<!\d)(?P<day>\d{1,2})[\s/-]+(?P<month_name>JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?),?[\s/-]+(?P<year>\d{4})(?!\d)" + _CLOCK_SUFFIX, re.I)),
    ("missing_year", re.compile(r"(?<![\d年/.-])(?P<month>\d{1,2})月(?P<day>\d{1,2})日\s*" + rf"(?:{_CLOCK})?", re.I)),
    ("relative_day", re.compile(r"(?P<relative_day>今天|今日|昨天|昨日)\s*" + rf"(?:{_CLOCK})?", re.I)),
    ("clock", re.compile(r"(?<!\d)" + _CLOCK, re.I)),
)
_MONTHS = {name: index for index, name in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}

_ROLE_LABELS = {
    "payment": ("支付时间", "付款时间", "支付日期", "付款日期", "还款时间", "还款日期", "PAID AT", "PAYMENT TIME"),
    "transaction": ("交易时间", "交易日期", "成交时间", "TRANSACTION TIME", "TRANSACTION DATE"),
    "consumption": ("消费时间", "消费日期", "扣款时间"),
    "refund": ("退款时间", "退款日期", "退回时间", "REFUND TIME"),
    "order": ("下单时间", "订单时间", "下单日期", "ORDER TIME"),
    "created": ("创建时间", "开票日期", "出票时间", "ISSUED AT"),
    "printed": ("打印时间", "打印日期", "重打时间", "PRINTED AT", "PRINT TIME"),
    "captured": ("截图时间", "截图日期", "接收时间", "通知时间", "来电时间", "CAPTURED AT", "RECEIVED AT"),
    "scheduled": ("预计扣款", "将于", "应还日期", "到期时间", "到期日期", "DUE DATE"),
}
NON_TRANSACTION_TIME_ROLES = frozenset({"refund", "order", "created", "printed", "captured", "scheduled"})


def is_time_fragment(literal: str, label: str) -> bool:
    """The notification wire accepts only a whole timestamp, never surrounding prose."""
    labels = {value for values in _ROLE_LABELS.values() for value in values}
    dated = re.sub(r"[ \t]*(?:UTC|GMT|CST|EST|PST)$", "", literal, flags=re.I)
    return (not label or label.upper() in labels) and any(pattern.fullmatch(dated) for _, pattern in _PATTERNS)


def _role(text: str, start: int, blocks: Sequence[dict] | None = None) -> tuple[str, int, str | None]:
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start]
    if not prefix.strip() and blocks:
        return _spatial_role(text, start, blocks)
    if not prefix.strip() and line_start:
        line_start = text.rfind("\n", 0, line_start - 1) + 1
        prefix = text[line_start:start]
    hits = [(match.end(), role, line_start + match.start(), match.group())
        for role, labels in _ROLE_LABELS.items() for label in labels
        for match in re.finditer(re.escape(label), prefix, re.I)]
    if hits:
        _end, role, position, label = max(hits)
        if not re.search(r"\d|[。；;]", text[position + len(label):start]):
            return role, position, label
    line_end = text.find("\n", start)
    line = text[line_start:line_end if line_end >= 0 else len(text)]
    if re.search(r"支出|消费|扣款|动账", line):
        return "transaction", start, "inline_business_time"
    return "unknown", start, None


def _time_label_role(label: str) -> str | None:
    # A bilingual label can repeat one role. Two different roles on the same
    # block do not identify which event the neighbouring value belongs to.
    if re.search(r"\d", label):
        return None
    roles = {role for role, aliases in _ROLE_LABELS.items()
        if any(re.search(re.escape(alias), label, re.I) for alias in aliases)}
    return next(iter(roles)) if len(roles) == 1 else None


def _same_time_row(left_box: Sequence, right_box: Sequence) -> bool:
    left_top, left_bottom = min(p[1] for p in left_box), max(p[1] for p in left_box)
    right_top, right_bottom = min(p[1] for p in right_box), max(p[1] for p in right_box)
    height = min(left_bottom - left_top, right_bottom - right_top)
    # Partial overlap tolerates skewed camera pages and differing glyph heights.
    return height > 0 and min(left_bottom, right_bottom) - max(left_top, right_top) >= height / 4


def _label_distance(label_box: Sequence, value_box: Sequence) -> tuple[int, float] | None:
    left, right = min(p[0] for p in value_box), max(p[0] for p in value_box)
    label_left, label_right = min(p[0] for p in label_box), max(p[0] for p in label_box)
    if label_right <= left and _same_time_row(label_box, value_box):
        return 0, left - label_right
    top = min(p[1] for p in value_box)
    bottom = max(p[1] for p in label_box)
    height = min(max(p[1] for p in value_box) - top, bottom - min(p[1] for p in label_box))
    overlap = min(right, label_right) - max(left, label_left)
    if height > 0 and 0 <= top - bottom <= height * 2 and overlap >= min(right - left, label_right - label_left) / 2:
        return 1, top - bottom
    return None


def _spatial_role(text: str, start: int, blocks: Sequence[dict]) -> tuple[str, int, str | None]:
    """Prefer same-row labels, then a nearby label above in the same column."""
    lines = text.splitlines()
    index = text.count("\n", 0, start)
    box = blocks[index]["box"]
    hits = []
    offset = 0
    for line, block in zip(lines, blocks, strict=True):
        label = line.strip(" :：")
        role = _time_label_role(label)
        distance = _label_distance(block["box"], box)
        if role is not None and distance is not None:
            hits.append((distance, role, offset + line.index(label), label))
        offset += len(line) + 1
    if not hits:
        return "unknown", start, None
    nearest = min(item[0] for item in hits)
    winners = [item for item in hits if item[0] == nearest]
    if len({item[1] for item in winners}) != 1:
        return "unknown", start, None
    _, role, position, label = winners[0]
    return role, position, label


def _zone(name: str | None):
    resolved = (name or "").strip() or get_settings().ocr_default_timezone
    try:
        return ZoneInfo(resolved), "source_timezone" if name else "configured_timezone"
    except (ZoneInfoNotFoundError, ValueError):
        return None, "invalid_timezone"


def _local_instant(local: datetime, zone) -> tuple[datetime | None, str | None]:
    # A round trip detects nonexistent/ambiguous wall times; fold=0 would guess.
    choices = {aware.astimezone(UTC) for fold in (0, 1)
        if (aware := local.replace(tzinfo=zone, fold=fold)).astimezone(UTC)
        .astimezone(zone).replace(tzinfo=None) == local}
    if len(choices) != 1:
        return None, "ambiguous_timezone" if choices else "nonexistent_local_time"
    return choices.pop(), None


def _printed_zone(value: str):
    offset = re.sub(r"UTC|GMT", "", value.upper())
    if offset == "Z":
        return UTC
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", offset)
    if match is None:
        raise ValueError("Incomplete UTC offset")
    sign, hours, minutes = match.groups()
    hours, minutes = int(hours), int(minutes)
    if hours > 14 or minutes > 59 or (hours == 14 and minutes):
        raise ValueError("Invalid UTC offset")
    return timezone(timedelta(minutes=(hours * 60 + minutes) * (-1 if sign == "-" else 1)))


def _dates(
    kind: str, groups: dict[str, str | None], reference: datetime | None, zone: tzinfo | None,
) -> list[tuple[date | None, tuple[str, ...], str | None]]:
    if kind == "clock":
        return [(None, ("date",), "date_missing")]
    if kind == "relative_day":
        if reference is None or zone is None:
            return [(None, ("date",), "reference_time_missing")]
        day = reference.astimezone(zone).date() - timedelta(days=groups["relative_day"] in {"昨天", "昨日"})
        return [(day, ("date",), "date_inferred_from_capture_reference")]
    month = _MONTHS[groups["month_name"][:3].upper()] if groups.get("month_name") else int(groups.get("month") or 1)
    day = int(groups.get("day") or 1)
    if kind == "missing_year":
        return _missing_year_dates(month, day, reference, zone)
    if kind == "day_month":
        return _day_month_dates(int(groups["first"]), int(groups["last"]), int(groups["year"]))
    try:
        return [(date(int(groups["year"]), month, day), (), None)]
    except ValueError:
        return [(None, (), "invalid_date")]


def _missing_year_dates(month, day, reference, zone):
    if reference is None or zone is None:
        return [(None, ("year",), "reference_time_missing")]
    reference_day = reference.astimezone(zone).date()
    choices = []
    for year in (reference_day.year, reference_day.year - 1):
        try:
            value = date(year, month, day)
        except ValueError:
            continue
        if value <= reference_day:
            choices.append(value)
    return [(max(choices) if choices else None, ("year",), "year_inferred_from_capture_reference")]


def _day_month_dates(first: int, last: int, year: int):
    choices = set()
    for month, day in ((last, first), (first, last)):
        try:
            choices.add(date(year, month, day))
        except ValueError:
            continue
    reason = "ambiguous_date_order" if len(choices) > 1 else None
    return [(value, (), reason) for value in sorted(choices)] or [(None, (), "invalid_date")]


def _clock_time(groups: dict[str, str | None]) -> time:
    hour, minute, second = int(groups["hour"]), int(groups["minute"]), int(groups.get("second") or 0)
    ampm = (groups.get("ampm") or "").upper()
    period = groups.get("period")
    if ampm or period:
        if not 1 <= hour <= 12:
            raise ValueError("Invalid twelve-hour clock")
        if period in {"上午", "晚上"} and hour == 12:
            raise ValueError("Ambiguous Chinese noon or midnight")
        hour = hour % 12 + (12 if ampm == "PM" or period in {"下午", "晚上"} else 0)
    return time(hour, minute, second)


def _candidate(
    text: str, match: re.Match, kind: str, day: date | None, inferred: tuple[str, ...],
    reason: str | None, zone: tzinfo | None, zone_basis: str, reference: datetime | None,
    blocks: Sequence[dict] | None = None,
) -> _TimeCandidate:
    groups = match.groupdict()
    role, start, label = _role(text, match.start(), blocks)
    label_span = None
    if blocks and label and text.count("\n", 0, start) != text.count("\n", 0, match.start()):
        label_span = (start, start + len(label))
        start = match.start()
    score = {"transaction": 100, "payment": 100, "consumption": 100, "unknown": 60}.get(role, 20)
    precision = "second" if groups.get("second") else "minute" if groups.get("hour") else "date_only"
    local_value = day.isoformat() if day else match.group()
    unresolved_zone = re.match(r"[ \t]*(?:UTC|GMT|CST|EST|PST|[+-])[A-Za-z0-9:+-]*", text[match.end():], re.I)
    candidate = _TimeCandidate(value=local_value, score=score,
        line_index=_line_index_for_offset(text, start), source=f"time:{kind}",
        evidence=(), dimensions=_ScoreDimensions(), role=role, precision=precision,
        local_value=local_value, timezone_name=str(zone) if zone else None, timezone_basis=zone_basis,
        inferred_components=inferred, review_reason=reason,
        normalized_span=(start, match.end() + (unresolved_zone.end() if unresolved_zone else 0)), label_span=label_span)
    candidate, zone = _resolve_clock(candidate, groups, day, zone, bool(unresolved_zone))
    candidate = _review_capture_date(candidate, day, reference, zone)
    evidence = (match.group(), f"time_role:{role}", f"precision:{precision}")
    if label:
        evidence += (f"label:{label}",)
    if candidate.review_reason:
        evidence += (candidate.review_reason,)
    return replace(candidate, evidence=evidence, dimensions=_ScoreDimensions(label=score, evidence=evidence))


def _resolve_clock(candidate: _TimeCandidate, groups: dict[str, str | None], day: date | None,
        zone: tzinfo | None, unresolved_zone: bool) -> tuple[_TimeCandidate, tzinfo | None]:
    try:
        if unresolved_zone:
            raise ValueError("Unresolved or malformed printed timezone")
        clock = _clock_time(groups) if groups.get("hour") else None
        if clock is None:
            candidate = replace(candidate, review_reason=candidate.review_reason or "date_only")
        elif day is not None:
            local = datetime.combine(day, clock)
            local_value = local.isoformat(timespec="seconds" if candidate.precision == "second" else "minutes")
            candidate = replace(candidate, value=local_value, local_value=local_value)
            if groups.get("offset"):
                zone = _printed_zone(groups["offset"])
                candidate = replace(candidate, timezone_basis="printed_offset")
            instant, timezone_reason = _local_instant(local, zone) if zone is not None else (None, "invalid_timezone")
            utc_offset = int(instant.astimezone(zone).utcoffset().total_seconds()) if instant is not None else None
            candidate = replace(candidate, value=instant or local_value, local_value=local_value,
                timezone_name=str(zone) if zone else None, utc_offset_seconds=utc_offset,
                review_reason=candidate.review_reason or timezone_reason)
    except (ValueError, OverflowError):
        candidate = replace(candidate, review_reason="invalid_datetime")
    return candidate, zone


def _review_capture_date(candidate, day, reference, zone):
    reason = candidate.review_reason
    after_capture = day is not None and reference is not None and zone is not None and day > reference.astimezone(zone).date()
    if after_capture and reason in {None, "date_only"}:
        reason = "after_capture_date"
    if candidate.role in NON_TRANSACTION_TIME_ROLES:
        reason = "non_transaction_time"
    return replace(candidate, review_reason=reason,
        reference_time=reference.isoformat() if (candidate.inferred_components or after_capture) and reference else None)


def _time_candidates(text: str, timezone_name: str | None = None, *, reference_time: datetime | None = None,
        evidence_blocks: Sequence[dict] | None = None) -> list[_TimeCandidate]:
    # Never consult datetime.now(): retrying a frozen image must not change its year.
    reference = reference_time if reference_time is not None and reference_time.utcoffset() is not None else None
    zone, basis = _zone(timezone_name)
    candidates = []
    occupied = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            if any(start < match.end() and match.start() < end for start, end in occupied):
                continue
            occupied.append(match.span())
            if kind == "clock" and _role(text, match.start(), evidence_blocks)[0] == "unknown":
                continue  # Status-bar clocks cannot establish transaction evidence.
            for day, inferred, reason in _dates(kind, match.groupdict(), reference, zone):
                candidates.append(_candidate(text, match, kind, day, inferred, reason, zone, basis, reference, evidence_blocks))
    return candidates


def compatible_times(left: _TimeCandidate, right: _TimeCandidate) -> bool:
    if isinstance(left.value, datetime) and isinstance(right.value, datetime):
        if left.precision == "minute" or right.precision == "minute":
            return left.value.replace(second=0, microsecond=0) == right.value.replace(second=0, microsecond=0)
        return left.value == right.value
    if left.precision == "date_only" and isinstance(right.value, datetime):
        return left.local_value == (right.local_value or "").split("T")[0]
    if right.precision == "date_only" and isinstance(left.value, datetime):
        return compatible_times(right, left)
    return left.value == right.value

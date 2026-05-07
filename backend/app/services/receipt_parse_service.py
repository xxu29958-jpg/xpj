from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.category_service import normalize_category
from app.services.receipt_parse_rules import (
    AMOUNT_LABEL_SCORES,
    BANK_KEYWORDS,
    CATEGORY_HINT_RULES,
    CLOCK_LINE_PATTERN,
    DISCOUNT_AMOUNT_LABELS,
    INLINE_AMOUNT_PATTERNS,
    LABELED_AMOUNT_PATTERN,
    MERCHANT_IGNORED_LINES,
    MERCHANT_KEYWORDS,
    MERCHANT_LABEL_PATTERN,
    MERCHANT_LABEL_SCORES,
    MERCHANT_REJECT_SUBSTRINGS,
    MONEY_MARKERS,
    PAYMENT_METHOD_LINE_PATTERN,
    PRIMARY_AMOUNT_LINE_PATTERN,
    SUCCESS_PAGE_AD_KEYWORDS,
    SUCCESS_PAGE_SKIP_LINES,
    TIME_PATTERNS,
    TRANSACTION_SUCCESS_KEYWORDS,
    UPPER_MONEY_MARKERS,
)
from app.services.time_service import ensure_utc


@dataclass(frozen=True)
class ParsedReceipt:
    amount_cents: int | None = None
    merchant: str | None = None
    expense_time: datetime | None = None
    category: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class _AmountCandidate:
    amount_cents: int
    score: int
    line_index: int
    source: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class _MerchantCandidate:
    value: str
    score: int
    line_index: int
    source: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class _TimeCandidate:
    value: datetime
    score: int
    line_index: int
    source: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class _CategoryCandidate:
    category: str
    score: int
    line_index: int
    source: str
    evidence: tuple[str, ...] = ()


class _RankedCandidate(Protocol):
    score: int
    line_index: int


_CandidateT = TypeVar("_CandidateT", bound=_RankedCandidate)


def parse_receipt_text(raw_text: str) -> ParsedReceipt:
    text = _normalize_text(raw_text)
    if not text:
        return ParsedReceipt()

    amount_candidate = _best_candidate(_amount_candidates(text))
    merchant_candidate = _best_candidate(_merchant_candidates(text))
    time_candidate = _best_candidate(_time_candidates(text))
    amount_cents = amount_candidate.amount_cents if amount_candidate else None
    merchant = merchant_candidate.value if merchant_candidate else None
    expense_time = time_candidate.value if time_candidate else None
    category_candidate = _best_candidate(_category_candidates(text, merchant))
    category = category_candidate.category if category_candidate else None
    confidence = _estimate_confidence(
        amount_candidate=amount_candidate,
        merchant_candidate=merchant_candidate,
        time_candidate=time_candidate,
        category_candidate=category_candidate,
        raw_text=text,
    )

    return ParsedReceipt(
        amount_cents=amount_cents,
        merchant=merchant,
        expense_time=expense_time,
        category=category,
        confidence=confidence,
    )


def _normalize_text(raw_text: str) -> str:
    return "\n".join(line.strip() for line in raw_text.replace("\r", "\n").splitlines() if line.strip())


def _extract_amount_cents(text: str) -> int | None:
    candidate = _best_candidate(_amount_candidates(text))
    return candidate.amount_cents if candidate else None


def _best_candidate(candidates: list[_CandidateT]) -> _CandidateT | None:
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate.score, -candidate.line_index))


def _amount_candidates(text: str) -> list[_AmountCandidate]:
    lines = text.splitlines()
    candidates: list[_AmountCandidate] = []

    for index, line in enumerate(lines):
        line_text = line.strip()
        match = PRIMARY_AMOUNT_LINE_PATTERN.match(line_text)
        if match:
            cents = _money_to_cents(match.group("amount"))
            if cents is not None and 0 < cents < 10_000_000_00:
                has_money_marker = _has_money_marker(line_text)
                has_nearby_success = _has_nearby_success(lines, index)
                if not (has_money_marker or has_nearby_success or match.group("sign")):
                    continue
                score = 32 if has_money_marker else 24
                evidence = [f"line:{line_text}"]
                if has_money_marker:
                    evidence.append("money_marker")
                if has_nearby_success:
                    score = 90
                    evidence.append("near_transaction_success")
                if match.group("sign"):
                    score += 12
                    evidence.append("signed_primary_amount")
                if _has_discount_context(lines, index):
                    score -= 50
                    evidence.append("discount_context:-50")
                if score > 0:
                    candidates.append(_AmountCandidate(cents, score, index, "line", tuple(evidence)))

    for match in LABELED_AMOUNT_PATTERN.finditer(text):
        cents = _money_to_cents(match.group("amount"))
        if cents is None or not 0 < cents < 10_000_000_00:
            continue
        label = match.group("label")
        index = _line_index_for_offset(text, match.start())
        score = AMOUNT_LABEL_SCORES.get(label, 35)
        evidence = [f"label:{label}"]
        if _has_discount_context(lines, index):
            score -= 45
            evidence.append("discount_context:-45")
        candidates.append(_AmountCandidate(cents, score, index, f"label:{label}", tuple(evidence)))

    for pattern, source, base_score in INLINE_AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            cents = _money_to_cents(match.group("amount"))
            if cents is None or not 0 < cents < 10_000_000_00:
                continue
            index = _line_index_for_offset(text, match.start())
            has_nearby_success = _has_nearby_success(lines, index)
            score = base_score + (42 if has_nearby_success else 0)
            evidence = [source]
            if has_nearby_success:
                evidence.append("near_transaction_success:+42")
            if _has_discount_context(lines, index):
                score -= 45
                evidence.append("discount_context:-45")
            if score > 0:
                candidates.append(_AmountCandidate(cents, score, index, source, tuple(evidence)))

    return candidates


def _line_index_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def _has_nearby_success(lines: list[str], index: int) -> bool:
    nearby = "\n".join(lines[max(0, index - 2) : min(len(lines), index + 3)])
    return any(keyword in nearby for keyword in TRANSACTION_SUCCESS_KEYWORDS)


def _has_discount_context(lines: list[str], index: int) -> bool:
    nearby = "\n".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
    return any(label in nearby for label in DISCOUNT_AMOUNT_LABELS)


def _has_money_marker(value: str) -> bool:
    upper_value = value.upper()
    return any(marker in value for marker in MONEY_MARKERS) or any(marker in upper_value for marker in UPPER_MONEY_MARKERS)


def _money_to_cents(value: str) -> int | None:
    try:
        amount = Decimal(value.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _extract_merchant(text: str) -> str | None:
    candidate = _best_candidate(_merchant_candidates(text))
    return candidate.value if candidate else None


def _merchant_candidates(text: str) -> list[_MerchantCandidate]:
    lines = text.splitlines()
    candidates: list[_MerchantCandidate] = []

    for index, line in enumerate(lines):
        if not any(keyword in line for keyword in TRANSACTION_SUCCESS_KEYWORDS):
            continue

        for candidate_index in range(index - 1, max(-1, index - 6), -1):
            cleaned = _clean_merchant(lines[candidate_index])
            distance = index - candidate_index
            candidate = _score_merchant_candidate(
                text=text,
                value=cleaned,
                base_score=104 - distance * 4,
                line_index=candidate_index,
                source="success_title",
                require_no_digits=False,
            )
            if candidate:
                candidates.append(candidate)

        if line.strip() == "支付成功":
            for candidate_index in range(index + 1, min(len(lines), index + 10)):
                cleaned = _clean_merchant(lines[candidate_index])
                distance = candidate_index - index
                candidate = _score_merchant_candidate(
                    text=text,
                    value=cleaned,
                    base_score=94 - distance * 3,
                    line_index=candidate_index,
                    source="success_body",
                    require_no_digits=True,
                )
                if candidate:
                    candidates.append(candidate)

    for index, line in enumerate(lines):
        if not PAYMENT_METHOD_LINE_PATTERN.match(line.strip()):
            continue
        for candidate_index in range(index - 1, max(-1, index - 4), -1):
            cleaned = _clean_merchant(lines[candidate_index])
            distance = index - candidate_index
            candidate = _score_merchant_candidate(
                text=text,
                value=cleaned,
                base_score=90 - distance * 4,
                line_index=candidate_index,
                source="payment_method_previous_line",
                require_no_digits=False,
            )
            if candidate:
                candidates.append(candidate)

    for match in MERCHANT_LABEL_PATTERN.finditer(text):
        cleaned = _clean_merchant(match.group("value"))
        label = match.group("label")
        index = _line_index_for_offset(text, match.start())
        base_score = MERCHANT_LABEL_SCORES.get(label, 50)
        candidate = _score_merchant_candidate(
            text=text,
            value=cleaned,
            base_score=base_score,
            line_index=index,
            source=f"label:{label}",
            require_no_digits=False,
        )
        if candidate:
            candidates.append(candidate)

    lower_text = text.lower()
    for keyword in MERCHANT_KEYWORDS:
        if keyword.lower() not in lower_text:
            continue
        base_score = 80 if _looks_like_bank_reminder(text, keyword) else 45
        candidate = _score_merchant_candidate(
            text=text,
            value=keyword,
            base_score=base_score,
            line_index=_line_index_for_offset(lower_text, lower_text.find(keyword.lower())),
            source="keyword",
            require_no_digits=False,
        )
        if candidate:
            candidates.append(candidate)

    first_line = text.splitlines()[0].strip()
    candidate = _score_merchant_candidate(
        text=text,
        value=_clean_merchant(first_line),
        base_score=35,
        line_index=0,
        source="first_line",
        require_no_digits=True,
    )
    if candidate:
        candidates.append(candidate)

    return candidates


def _score_merchant_candidate(
    *,
    text: str,
    value: str | None,
    base_score: int,
    line_index: int,
    source: str,
    require_no_digits: bool,
) -> _MerchantCandidate | None:
    if not _is_title_merchant_candidate(value):
        return None
    assert value is not None
    if require_no_digits and any(ch.isdigit() for ch in value):
        return None

    score = base_score
    evidence = [source, f"base:{base_score}"]
    if source != "keyword" and any(keyword in value for keyword in SUCCESS_PAGE_AD_KEYWORDS):
        score -= 60
        evidence.append("success_page_ad:-60")
    if value in SUCCESS_PAGE_SKIP_LINES:
        score -= 70
        evidence.append("success_page_skip:-70")
    if value in BANK_KEYWORDS and _looks_like_payment_institution_context(text, value):
        score -= 65
        evidence.append("payment_institution_context:-65")
    if len(value) > 24 and source == "success_body":
        score -= 45
        evidence.append("long_success_body:-45")
    if score < 25:
        return None
    return _MerchantCandidate(value=value, score=score, line_index=line_index, source=source, evidence=tuple(evidence))


def _is_title_merchant_candidate(value: str | None) -> bool:
    if not value:
        return False
    if value in MERCHANT_IGNORED_LINES:
        return False
    if PRIMARY_AMOUNT_LINE_PATTERN.match(value):
        return False
    if len(value) < 2 or len(value) > 30:
        return False
    upper_value = value.upper()
    if CLOCK_LINE_PATTERN.match(value) or "4G" in upper_value or "5G" in upper_value or "WIFI" in upper_value:
        return False
    if any(label in value for label in MERCHANT_REJECT_SUBSTRINGS):
        return False
    return True


def _looks_like_payment_institution_context(text: str, keyword: str) -> bool:
    if keyword not in text:
        return False
    if "交易提醒" in text and text.splitlines()[0].strip() == keyword:
        return False
    return any(label in text for label in ["收单机构", "清算机构", "收款方全称"])


def _looks_like_bank_reminder(text: str, keyword: str) -> bool:
    lines = text.splitlines()
    return keyword in BANK_KEYWORDS and bool(lines) and lines[0].strip() == keyword and "交易提醒" in text


def _clean_merchant(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" ：:，,。；;")
    return cleaned or None


def _extract_expense_time(text: str) -> datetime | None:
    candidate = _best_candidate(_time_candidates(text))
    return candidate.value if candidate else None


def _time_candidates(text: str) -> list[_TimeCandidate]:
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
                    tzinfo=_default_timezone(),
                )
            except ValueError:
                continue

            match_text = match.group(0)
            candidates.append(
                _TimeCandidate(
                    value=ensure_utc(local_value),
                    score=_score_time_match(match_text, pattern_index),
                    line_index=_line_index_for_offset(text, match.start()),
                    source=f"time_pattern:{pattern_index}",
                    evidence=(match_text,),
                )
            )
    return candidates


def _score_time_match(match_text: str, pattern_index: int) -> int:
    if any(label in match_text for label in ["交易时间", "支付时间", "付款时间", "消费时间"]):
        return 96
    if any(label in match_text for label in ["下单时间", "订单时间"]):
        return 76
    if any(label in match_text for label in ["创建时间", "来电时间"]):
        return 42
    if "时间" in match_text:
        return 50
    return 38 - pattern_index * 4


def _default_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().ocr_default_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def _suggest_category(text: str, merchant: str | None) -> str | None:
    candidate = _best_candidate(_category_candidates(text, merchant))
    return candidate.category if candidate else None


def _category_candidates(text: str, merchant: str | None) -> list[_CategoryCandidate]:
    merchant_text = (merchant or "").lower()
    full_text = f"{merchant or ''}\n{text}".lower()
    buckets: dict[str, _CategoryCandidate] = {}

    def add_candidate(rule_index: int, category: str, score: int, source: str, evidence: str) -> None:
        normalized = normalize_category(category)
        previous = buckets.get(normalized)
        if previous is None:
            buckets[normalized] = _CategoryCandidate(
                category=normalized,
                score=score,
                line_index=rule_index,
                source=source,
                evidence=(evidence,),
            )
            return

        buckets[normalized] = _CategoryCandidate(
            category=normalized,
            score=min(100, previous.score + min(8, max(3, score // 12))),
            line_index=min(previous.line_index, rule_index),
            source=previous.source,
            evidence=previous.evidence + (evidence,),
        )

    for rule_index, rule in enumerate(CATEGORY_HINT_RULES):
        for keyword in rule.keywords:
            lowered = keyword.lower()
            if merchant_text and lowered in merchant_text:
                add_candidate(rule_index, rule.category, 88, "merchant_keyword", f"merchant:{keyword}")
            elif lowered in full_text:
                add_candidate(rule_index, rule.category, 42, "text_keyword", f"text:{keyword}")

    return list(buckets.values())


def _estimate_confidence(
    *,
    amount_candidate: _AmountCandidate | None,
    merchant_candidate: _MerchantCandidate | None,
    time_candidate: _TimeCandidate | None,
    category_candidate: _CategoryCandidate | None,
    raw_text: str,
) -> float:
    score = 0.12
    if amount_candidate is not None:
        score += 0.35 * _score_ratio(amount_candidate.score)
    if merchant_candidate is not None:
        score += 0.22 * _score_ratio(merchant_candidate.score)
    if time_candidate is not None:
        score += 0.2 * _score_ratio(time_candidate.score)
    if category_candidate is not None:
        score += 0.06 * _score_ratio(category_candidate.score)
    if len(raw_text) >= 20:
        score += 0.1
    return round(min(score, 0.95), 4)


def _score_ratio(score: int) -> float:
    return max(0.0, min(score / 100, 1.0))

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
class _ScoreDimensions:
    source: int = 0
    label: int = 0
    context: int = 0
    proximity: int = 0
    profile: int = 0
    structure: int = 0
    consistency: int = 0
    noise: int = 0
    evidence: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return max(
            0,
            min(
                120,
                self.source
                + self.label
                + self.context
                + self.proximity
                + self.profile
                + self.structure
                + self.consistency
                + self.noise,
            ),
        )


@dataclass(frozen=True)
class _ReceiptContext:
    text: str
    lines: tuple[str, ...]
    profile: str


@dataclass(frozen=True)
class _AmountCandidate:
    amount_cents: int
    score: int
    line_index: int
    source: str
    evidence: tuple[str, ...] = ()
    dimensions: _ScoreDimensions | None = None


@dataclass(frozen=True)
class _MerchantCandidate:
    value: str
    score: int
    line_index: int
    source: str
    evidence: tuple[str, ...] = ()
    dimensions: _ScoreDimensions | None = None


@dataclass(frozen=True)
class _TimeCandidate:
    value: datetime
    score: int
    line_index: int
    source: str
    evidence: tuple[str, ...] = ()
    dimensions: _ScoreDimensions | None = None


@dataclass(frozen=True)
class _CategoryCandidate:
    category: str
    score: int
    line_index: int
    source: str
    evidence: tuple[str, ...] = ()
    dimensions: _ScoreDimensions | None = None


class _RankedCandidate(Protocol):
    score: int
    line_index: int


_CandidateT = TypeVar("_CandidateT", bound=_RankedCandidate)


def parse_receipt_text(raw_text: str) -> ParsedReceipt:
    text = _normalize_text(raw_text)
    if not text:
        return ParsedReceipt()

    context = _build_receipt_context(text)
    amount_candidate = _best_candidate(_calibrate_amount_candidates(_amount_candidates(text), context))
    merchant_candidate = _best_candidate(_calibrate_merchant_candidates(_merchant_candidates(text), context))
    time_candidate = _best_candidate(_calibrate_time_candidates(_time_candidates(text), context))
    amount_cents = amount_candidate.amount_cents if amount_candidate else None
    merchant = merchant_candidate.value if merchant_candidate else None
    expense_time = time_candidate.value if time_candidate else None
    category_candidate = _best_candidate(_calibrate_category_candidates(_category_candidates(text, merchant), context, merchant_candidate))
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


def _build_receipt_context(text: str) -> _ReceiptContext:
    lines = tuple(text.splitlines())
    return _ReceiptContext(text=text, lines=lines, profile=_detect_receipt_profile(text, lines))


def _detect_receipt_profile(text: str, lines: tuple[str, ...]) -> str:
    first_line = lines[0].strip() if lines else ""
    if first_line in BANK_KEYWORDS and "交易提醒" in text:
        return "bank_reminder"
    if "账单详情" in text and "交易成功" in text and any(label in text for label in ["订单金额", "支付时间", "付款方式"]):
        return "alipay_bill_detail"
    if "支付成功" in text and ("获得森林能量" in text or "交易方式" in text or "花呗" in text):
        return "alipay_success_page"
    if "微信支付" in text and any(label in text for label in ["交易状态", "账单详情", "使用"]):
        return "wechat_payment_detail"
    if "高德" in text and any(label in text for label in ["打车", "费用说明", "确认支付"]):
        return "mobility_payment"
    return "generic"


def _extract_amount_cents(text: str) -> int | None:
    context = _build_receipt_context(text)
    candidate = _best_candidate(_calibrate_amount_candidates(_amount_candidates(text), context))
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
                evidence = [f"line:{line_text}"]
                if has_money_marker:
                    evidence.append("money_marker")
                if match.group("sign"):
                    evidence.append("signed_primary_amount")
                has_discount_context = _has_discount_context(lines, index)
                if has_discount_context:
                    evidence.append("discount_context:-50")
                dimensions = _ScoreDimensions(
                    source=28 if has_money_marker else 24,
                    context=62 if has_nearby_success else 0,
                    label=12 if match.group("sign") else 0,
                    consistency=_amount_plausibility_score(cents),
                    noise=-50 if has_discount_context else 0,
                    evidence=tuple(evidence),
                )
                score = dimensions.total
                if score > 0:
                    candidates.append(
                        _AmountCandidate(
                            amount_cents=cents,
                            score=score,
                            line_index=index,
                            source="line",
                            evidence=dimensions.evidence,
                            dimensions=dimensions,
                        )
                    )

    for match in LABELED_AMOUNT_PATTERN.finditer(text):
        cents = _money_to_cents(match.group("amount"))
        if cents is None or not 0 < cents < 10_000_000_00:
            continue
        label = match.group("label")
        index = _line_index_for_offset(text, match.start())
        evidence = [f"label:{label}"]
        has_discount_context = _has_discount_context(lines, index)
        has_nearby_success = _has_nearby_success(lines, index)
        if has_discount_context:
            evidence.append("discount_context:-45")
        if has_nearby_success:
            evidence.append("near_transaction_success:+10")
        dimensions = _ScoreDimensions(
            label=AMOUNT_LABEL_SCORES.get(label, 35),
            context=10 if has_nearby_success else 0,
            consistency=_amount_plausibility_score(cents),
            noise=-45 if has_discount_context else 0,
            evidence=tuple(evidence),
        )
        candidates.append(
            _AmountCandidate(
                amount_cents=cents,
                score=dimensions.total,
                line_index=index,
                source=f"label:{label}",
                evidence=dimensions.evidence,
                dimensions=dimensions,
            )
        )

    for pattern, source, base_score in INLINE_AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            cents = _money_to_cents(match.group("amount"))
            if cents is None or not 0 < cents < 10_000_000_00:
                continue
            index = _line_index_for_offset(text, match.start())
            has_nearby_success = _has_nearby_success(lines, index)
            evidence = [source]
            if has_nearby_success:
                evidence.append("near_transaction_success:+42")
            has_discount_context = _has_discount_context(lines, index)
            if has_discount_context:
                evidence.append("discount_context:-45")
            dimensions = _ScoreDimensions(
                source=base_score,
                context=42 if has_nearby_success else 0,
                consistency=_amount_plausibility_score(cents),
                noise=-45 if has_discount_context else 0,
                evidence=tuple(evidence),
            )
            score = dimensions.total
            if score > 0:
                candidates.append(_AmountCandidate(cents, score, index, source, dimensions.evidence, dimensions))

    return _apply_amount_cross_evidence(candidates)


def _calibrate_amount_candidates(candidates: list[_AmountCandidate], context: _ReceiptContext) -> list[_AmountCandidate]:
    has_signed_primary_near_success = any(
        candidate.source == "line"
        and any("signed_primary_amount" in evidence for evidence in candidate.evidence)
        and any("near_transaction_success" in evidence for evidence in candidate.evidence)
        for candidate in candidates
    )

    calibrated: list[_AmountCandidate] = []
    for candidate in candidates:
        profile = 0
        structure = 0
        noise = 0
        evidence: list[str] = []

        if context.profile == "alipay_bill_detail":
            if candidate.source == "line" and any("signed_primary_amount" in item for item in candidate.evidence):
                profile += 14
                evidence.append("profile_alipay_detail_primary:+14")
            if candidate.source == "label:订单金额" and has_signed_primary_near_success:
                noise -= 28
                evidence.append("profile_alipay_detail_order_amount:-28")
        elif context.profile == "alipay_success_page":
            if candidate.source in {"line", "currency"} and any("near_transaction_success" in item for item in candidate.evidence):
                profile += 10
                evidence.append("profile_alipay_success_amount:+10")
        elif context.profile == "bank_reminder":
            if candidate.source.startswith("label:交易金额"):
                profile += 12
                evidence.append("profile_bank_transaction_amount:+12")
        elif context.profile == "mobility_payment":
            if candidate.source in {"yuan", "currency"}:
                structure += 8
                evidence.append("profile_mobility_inline_amount:+8")

        if profile == 0 and structure == 0 and noise == 0:
            calibrated.append(candidate)
            continue

        dimensions = _merge_dimensions(candidate.dimensions, profile=profile, structure=structure, noise=noise, evidence=tuple(evidence))
        calibrated.append(
            _AmountCandidate(
                amount_cents=candidate.amount_cents,
                score=dimensions.total,
                line_index=candidate.line_index,
                source=candidate.source,
                evidence=dimensions.evidence,
                dimensions=dimensions,
            )
        )
    return calibrated


def _amount_plausibility_score(cents: int) -> int:
    if cents < 50:
        return -8
    if cents <= 200_000:
        return 8
    if cents <= 1_000_000:
        return 2
    return -4


def _apply_amount_cross_evidence(candidates: list[_AmountCandidate]) -> list[_AmountCandidate]:
    counts: dict[int, int] = {}
    sources: dict[int, set[str]] = {}
    for candidate in candidates:
        counts[candidate.amount_cents] = counts.get(candidate.amount_cents, 0) + 1
        sources.setdefault(candidate.amount_cents, set()).add(candidate.source)

    boosted: list[_AmountCandidate] = []
    for candidate in candidates:
        support = min(16, max(0, counts[candidate.amount_cents] - 1) * 6 + max(0, len(sources[candidate.amount_cents]) - 1) * 4)
        if support <= 0:
            boosted.append(candidate)
            continue
        dimensions = _merge_dimensions(
            candidate.dimensions,
            consistency=support,
            evidence=(f"same_amount_support:+{support}",),
        )
        boosted.append(
            _AmountCandidate(
                amount_cents=candidate.amount_cents,
                score=dimensions.total,
                line_index=candidate.line_index,
                source=candidate.source,
                evidence=dimensions.evidence,
                dimensions=dimensions,
            )
        )
    return boosted


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
    context = _build_receipt_context(text)
    candidate = _best_candidate(_calibrate_merchant_candidates(_merchant_candidates(text), context))
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


def _calibrate_merchant_candidates(candidates: list[_MerchantCandidate], context: _ReceiptContext) -> list[_MerchantCandidate]:
    calibrated: list[_MerchantCandidate] = []
    for candidate in candidates:
        profile = 0
        structure = 0
        noise = 0
        evidence: list[str] = []

        if context.profile == "bank_reminder":
            if candidate.value in BANK_KEYWORDS and candidate.source in {"keyword", "first_line"}:
                profile += 22
                evidence.append("profile_bank_first_party:+22")
        elif context.profile == "alipay_bill_detail":
            if candidate.source == "success_title":
                profile += 16
                evidence.append("profile_alipay_detail_success_title:+16")
            if candidate.source.startswith("label:收款方") or (
                candidate.source in {"keyword", "first_line"} and candidate.value in BANK_KEYWORDS
            ):
                noise -= 28
                evidence.append("profile_alipay_detail_institution_noise:-28")
        elif context.profile == "alipay_success_page":
            if candidate.source == "success_body":
                profile += 18
                evidence.append("profile_alipay_success_body:+18")
            if candidate.value in {"高德", "支付宝"}:
                noise -= 20
                evidence.append("profile_alipay_success_ad_platform:-20")
        elif context.profile == "wechat_payment_detail":
            if candidate.source == "payment_method_previous_line":
                profile += 16
                evidence.append("profile_wechat_payment_previous_line:+16")
            if candidate.value in {"微信支付", "支付服务"}:
                noise -= 28
                evidence.append("profile_wechat_platform_noise:-28")
        elif context.profile == "mobility_payment":
            if candidate.value == "高德" or "打车" in candidate.value:
                profile += 18
                evidence.append("profile_mobility_provider:+18")

        if any(keyword.lower() in candidate.value.lower() for keyword in ["收单机构", "清算机构", "收款方全称"]):
            noise -= 18
            evidence.append("institution_label_noise:-18")

        if profile == 0 and structure == 0 and noise == 0:
            calibrated.append(candidate)
            continue

        dimensions = _merge_dimensions(candidate.dimensions, profile=profile, structure=structure, noise=noise, evidence=tuple(evidence))
        calibrated.append(
            _MerchantCandidate(
                value=candidate.value,
                score=dimensions.total,
                line_index=candidate.line_index,
                source=candidate.source,
                evidence=dimensions.evidence,
                dimensions=dimensions,
            )
        )
    return calibrated


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
    noise = 0
    if source != "keyword" and any(keyword in value for keyword in SUCCESS_PAGE_AD_KEYWORDS):
        noise -= 60
        evidence.append("success_page_ad:-60")
    if value in SUCCESS_PAGE_SKIP_LINES:
        noise -= 70
        evidence.append("success_page_skip:-70")
    if value in BANK_KEYWORDS and _looks_like_payment_institution_context(text, value):
        noise -= 65
        evidence.append("payment_institution_context:-65")
    if len(value) > 24 and source == "success_body":
        noise -= 45
        evidence.append("long_success_body:-45")
    dimensions = _ScoreDimensions(
        source=_merchant_source_score(source, base_score),
        proximity=_merchant_proximity_score(source, base_score),
        consistency=_merchant_consistency_score(text, value, source),
        noise=noise,
        evidence=tuple(evidence),
    )
    score = dimensions.total
    if score < 25:
        return None
    return _MerchantCandidate(value=value, score=score, line_index=line_index, source=source, evidence=dimensions.evidence, dimensions=dimensions)


def _merchant_source_score(source: str, base_score: int) -> int:
    if source == "success_title":
        return 72
    if source == "success_body":
        return 58
    if source == "payment_method_previous_line":
        return 54
    if source.startswith("label:"):
        return min(base_score, 64)
    if source == "keyword":
        return min(base_score, 52)
    if source == "first_line":
        return 28
    return min(base_score, 45)


def _merchant_proximity_score(source: str, base_score: int) -> int:
    if source in {"success_title", "success_body", "payment_method_previous_line"}:
        return max(0, min(24, base_score - _merchant_source_score(source, base_score)))
    return 0


def _merchant_consistency_score(text: str, value: str, source: str) -> int:
    score = 0
    lower_text = text.lower()
    lower_value = value.lower()
    if lower_value in lower_text:
        score += 6
    if value in MERCHANT_KEYWORDS:
        score += 8
    if source == "keyword" and _looks_like_bank_reminder(text, value):
        score += 18
    if any(keyword.lower() in lower_value for keyword in ["超市", "便利店", "外卖", "零食", "小吃", "餐", "打车"]):
        score += 6
    return min(score, 28)


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
    context = _build_receipt_context(text)
    candidate = _best_candidate(_calibrate_time_candidates(_time_candidates(text), context))
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
    return candidates


def _score_time_match(match_text: str, pattern_index: int) -> int:
    return _score_time_dimensions(match_text, pattern_index).total


def _score_time_dimensions(match_text: str, pattern_index: int) -> _ScoreDimensions:
    evidence = [match_text]
    if any(label in match_text for label in ["交易时间", "支付时间", "付款时间", "消费时间"]):
        return _ScoreDimensions(label=78, context=18, evidence=tuple(evidence + ["business_time"]))
    if any(label in match_text for label in ["下单时间", "订单时间"]):
        return _ScoreDimensions(label=62, context=12, evidence=tuple(evidence + ["order_time"]))
    if any(label in match_text for label in ["创建时间", "来电时间"]):
        return _ScoreDimensions(label=34, context=6, evidence=tuple(evidence + ["generic_event_time"]))
    if "时间" in match_text:
        return _ScoreDimensions(label=42, context=8, evidence=tuple(evidence + ["generic_time"]))
    return _ScoreDimensions(source=max(18, 38 - pattern_index * 4), evidence=tuple(evidence + ["plain_datetime"]))


def _calibrate_time_candidates(candidates: list[_TimeCandidate], context: _ReceiptContext) -> list[_TimeCandidate]:
    calibrated: list[_TimeCandidate] = []
    for candidate in candidates:
        profile = 0
        noise = 0
        evidence: list[str] = []
        evidence_text = "\n".join(candidate.evidence)
        if context.profile in {"alipay_bill_detail", "bank_reminder"} and any(label in evidence_text for label in ["交易时间", "支付时间", "付款时间"]):
            profile += 10
            evidence.append(f"profile_{context.profile}_business_time:+10")
        if context.profile != "mobility_payment" and any(label in evidence_text for label in ["创建时间", "来电时间"]):
            noise -= 10
            evidence.append("non_business_time_noise:-10")

        if profile == 0 and noise == 0:
            calibrated.append(candidate)
            continue

        dimensions = _merge_dimensions(candidate.dimensions, profile=profile, noise=noise, evidence=tuple(evidence))
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


def _default_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().ocr_default_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def _suggest_category(text: str, merchant: str | None) -> str | None:
    context = _build_receipt_context(text)
    merchant_candidate = _best_candidate(_calibrate_merchant_candidates(_merchant_candidates(text), context))
    candidate = _best_candidate(_calibrate_category_candidates(_category_candidates(text, merchant), context, merchant_candidate))
    return candidate.category if candidate else None


def _category_candidates(text: str, merchant: str | None) -> list[_CategoryCandidate]:
    merchant_text = (merchant or "").lower()
    full_text = f"{merchant or ''}\n{text}".lower()
    buckets: dict[str, _CategoryCandidate] = {}

    def add_candidate(rule_index: int, category: str, score: int, source: str, evidence: str) -> None:
        normalized = normalize_category(category)
        dimensions = _ScoreDimensions(
            source=score if source == "merchant_keyword" else 0,
            context=score if source == "text_keyword" else 0,
            consistency=10 if merchant_text and evidence.startswith("merchant:") else 0,
            evidence=(evidence,),
        )
        previous = buckets.get(normalized)
        if previous is None:
            buckets[normalized] = _CategoryCandidate(
                category=normalized,
                score=dimensions.total,
                line_index=rule_index,
                source=source,
                evidence=dimensions.evidence,
                dimensions=dimensions,
            )
            return

        merged = _merge_dimensions(
            previous.dimensions,
            context=4 if source == "text_keyword" else 0,
            consistency=8 if source == "merchant_keyword" else 3,
            evidence=(evidence,),
        )
        buckets[normalized] = _CategoryCandidate(
            category=normalized,
            score=merged.total,
            line_index=min(previous.line_index, rule_index),
            source=previous.source,
            evidence=merged.evidence,
            dimensions=merged,
        )

    for rule_index, rule in enumerate(CATEGORY_HINT_RULES):
        for keyword in rule.keywords:
            lowered = keyword.lower()
            if merchant_text and lowered in merchant_text:
                add_candidate(rule_index, rule.category, 88, "merchant_keyword", f"merchant:{keyword}")
            elif lowered in full_text:
                add_candidate(rule_index, rule.category, 42, "text_keyword", f"text:{keyword}")

    return list(buckets.values())


def _calibrate_category_candidates(
    candidates: list[_CategoryCandidate],
    context: _ReceiptContext,
    merchant_candidate: _MerchantCandidate | None,
) -> list[_CategoryCandidate]:
    calibrated: list[_CategoryCandidate] = []
    merchant_value = merchant_candidate.value if merchant_candidate else ""
    for candidate in candidates:
        profile = 0
        consistency = 0
        noise = 0
        evidence: list[str] = []

        if merchant_value and any(item.startswith("merchant:") for item in candidate.evidence):
            consistency += 10
            evidence.append("merchant_category_alignment:+10")
        if context.profile == "mobility_payment" and candidate.category == "交通":
            profile += 16
            evidence.append("profile_mobility_transport:+16")
        if context.profile == "alipay_success_page" and candidate.category == "交通" and merchant_value != "高德":
            noise -= 20
            evidence.append("profile_alipay_ad_transport_noise:-20")

        if profile == 0 and consistency == 0 and noise == 0:
            calibrated.append(candidate)
            continue

        dimensions = _merge_dimensions(candidate.dimensions, profile=profile, consistency=consistency, noise=noise, evidence=tuple(evidence))
        calibrated.append(
            _CategoryCandidate(
                category=candidate.category,
                score=dimensions.total,
                line_index=candidate.line_index,
                source=candidate.source,
                evidence=dimensions.evidence,
                dimensions=dimensions,
            )
        )
    return calibrated


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


def _merge_dimensions(
    dimensions: _ScoreDimensions | None,
    *,
    source: int = 0,
    label: int = 0,
    context: int = 0,
    proximity: int = 0,
    profile: int = 0,
    structure: int = 0,
    consistency: int = 0,
    noise: int = 0,
    evidence: tuple[str, ...] = (),
) -> _ScoreDimensions:
    base = dimensions or _ScoreDimensions()
    return _ScoreDimensions(
        source=base.source + source,
        label=base.label + label,
        context=base.context + context,
        proximity=base.proximity + proximity,
        profile=base.profile + profile,
        structure=base.structure + structure,
        consistency=base.consistency + consistency,
        noise=base.noise + noise,
        evidence=base.evidence + evidence,
    )

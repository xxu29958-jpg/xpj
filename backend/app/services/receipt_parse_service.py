from __future__ import annotations

# Candidate modules import shared dataclasses from this module, so their imports
# stay below the shared definitions.
# ruff: noqa: E402

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from app.services.receipt_parse_rules import (
    BANK_KEYWORDS,
    DISCOUNT_AMOUNT_LABELS,
    LABELED_AMOUNT_PATTERN,
    MERCHANT_LABEL_PATTERN,
    PAYMENT_SHEET_ACTION_MARKERS,
    PAYMENT_SHEET_MERCHANT_MARKERS,
    PAYMENT_SHEET_PAYMENT_METHOD_MARKERS,
    TIME_PATTERNS,
    TRANSACTION_SUCCESS_KEYWORDS,
)


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
    signals: "_ReceiptSignals"


@dataclass(frozen=True)
class _ReceiptSignals:
    line_count: int = 0
    transaction_success_count: int = 0
    amount_label_count: int = 0
    merchant_label_count: int = 0
    time_label_count: int = 0
    discount_marker_count: int = 0
    payment_sheet_marker_count: int = 0

    @property
    def structured_signal_count(self) -> int:
        return (
            self.transaction_success_count
            + self.amount_label_count
            + self.merchant_label_count
            + self.time_label_count
            + self.payment_sheet_marker_count
        )


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


def _normalize_text(raw_text: str) -> str:
    return "\n".join(
        line.strip()
        for line in raw_text.replace("\r", "\n").splitlines()
        if line.strip()
    )


def _build_receipt_context(text: str) -> _ReceiptContext:
    lines = tuple(text.splitlines())
    return _ReceiptContext(
        text=text,
        lines=lines,
        profile=_detect_receipt_profile(text, lines),
        signals=_build_receipt_signals(text, lines),
    )


def _build_receipt_signals(text: str, lines: tuple[str, ...]) -> _ReceiptSignals:
    return _ReceiptSignals(
        line_count=len(lines),
        transaction_success_count=sum(
            1 for keyword in TRANSACTION_SUCCESS_KEYWORDS if keyword in text
        ),
        amount_label_count=len(LABELED_AMOUNT_PATTERN.findall(text)),
        merchant_label_count=len(MERCHANT_LABEL_PATTERN.findall(text)),
        time_label_count=sum(len(pattern.findall(text)) for pattern in TIME_PATTERNS),
        discount_marker_count=sum(
            1 for marker in DISCOUNT_AMOUNT_LABELS if marker in text
        ),
        payment_sheet_marker_count=sum(
            1
            for marker in PAYMENT_SHEET_MERCHANT_MARKERS
            + PAYMENT_SHEET_ACTION_MARKERS
            + PAYMENT_SHEET_PAYMENT_METHOD_MARKERS
            if marker in text
        ),
    )


def _detect_receipt_profile(text: str, lines: tuple[str, ...]) -> str:
    first_line = lines[0].strip() if lines else ""
    if (first_line in BANK_KEYWORDS and "交易提醒" in text) or (
        "动账提醒" in text
        and any(marker in text for marker in ["支出人民币", "储蓄账户", "尾号"])
    ):
        return "bank_reminder"
    if any(marker in text for marker in PAYMENT_SHEET_MERCHANT_MARKERS) and any(
        marker in text for marker in PAYMENT_SHEET_ACTION_MARKERS
    ):
        return "taobao_flash_payment"
    if (
        "账单详情" in text
        and "交易成功" in text
        and any(label in text for label in ["订单金额", "支付时间", "付款方式"])
    ):
        return "alipay_bill_detail"
    if "支付成功" in text and (
        "获得森林能量" in text or "交易方式" in text or "花呗" in text
    ):
        return "alipay_success_page"
    if "微信支付" in text and any(
        label in text for label in ["交易状态", "账单详情", "使用"]
    ):
        return "wechat_payment_detail"
    if "高德" in text and any(
        label in text for label in ["打车", "费用说明", "确认支付"]
    ):
        return "mobility_payment"
    return "generic"


def _best_candidate(candidates: list[_CandidateT]) -> _CandidateT | None:
    if not candidates:
        return None
    return max(
        candidates, key=lambda candidate: (candidate.score, -candidate.line_index)
    )


def _line_index_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def _estimate_confidence(
    *,
    context: _ReceiptContext,
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
        score += 0.06
    score += _context_quality_bonus(
        context=context,
        amount_candidate=amount_candidate,
        merchant_candidate=merchant_candidate,
        time_candidate=time_candidate,
    )
    return round(min(score, 0.95), 4)


def _context_quality_bonus(
    *,
    context: _ReceiptContext,
    amount_candidate: _AmountCandidate | None,
    merchant_candidate: _MerchantCandidate | None,
    time_candidate: _TimeCandidate | None,
) -> float:
    signals = context.signals
    bonus = 0.0
    if context.profile != "generic":
        bonus += 0.03
    if signals.structured_signal_count >= 3:
        bonus += 0.03
    if signals.structured_signal_count >= 5:
        bonus += 0.02
    if amount_candidate is not None and merchant_candidate is not None:
        bonus += 0.03
    if amount_candidate is not None and time_candidate is not None:
        bonus += 0.02
    if signals.discount_marker_count and context.profile == "alipay_bill_detail":
        bonus += 0.01
    if signals.line_count < 3:
        bonus -= 0.04
    return max(-0.08, min(bonus, 0.11))


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


def _nearby_text(lines: tuple[str, ...], index: int, *, before: int, after: int) -> str:
    return "\n".join(lines[max(0, index - before) : min(len(lines), index + after + 1)])


def _first_marker_index(lines: tuple[str, ...], markers: tuple[str, ...]) -> int | None:
    for index, line in enumerate(lines):
        if any(marker in line for marker in markers):
            return index
    return None


def _is_before_payment_sheet(context: _ReceiptContext, line_index: int) -> bool:
    merchant_index = _first_marker_index(context.lines, PAYMENT_SHEET_MERCHANT_MARKERS)
    return merchant_index is not None and line_index < merchant_index


def _is_payment_sheet_amount(
    context: _ReceiptContext, candidate: _AmountCandidate
) -> bool:
    merchant_index = _first_marker_index(context.lines, PAYMENT_SHEET_MERCHANT_MARKERS)
    action_index = _first_marker_index(context.lines, PAYMENT_SHEET_ACTION_MARKERS)
    if merchant_index is None:
        return False

    lower_bound = merchant_index
    upper_bound = (
        action_index
        if action_index is not None
        else min(len(context.lines), merchant_index + 5)
    )
    if lower_bound <= candidate.line_index <= upper_bound:
        return True

    nearby = _nearby_text(context.lines, candidate.line_index, before=2, after=2)
    return any(
        marker in nearby
        for marker in PAYMENT_SHEET_MERCHANT_MARKERS
        + PAYMENT_SHEET_PAYMENT_METHOD_MARKERS
    )


from app.services.receipt_parse_amount import (
    _amount_candidates,
    _calibrate_amount_candidates,
)
from app.services.receipt_parse_category import (
    _calibrate_category_candidates,
    _category_candidates,
)
from app.services.receipt_parse_merchant import (
    _calibrate_merchant_candidates,
    _merchant_candidates,
)
from app.services.receipt_parse_time import (
    _calibrate_time_candidates,
    _time_candidates,
)


def parse_receipt_text(
    raw_text: str, timezone_name: str | None = None
) -> ParsedReceipt:
    text = _normalize_text(raw_text)
    if not text:
        return ParsedReceipt()

    context = _build_receipt_context(text)
    amount_candidate = _best_candidate(
        _calibrate_amount_candidates(_amount_candidates(text), context)
    )
    merchant_candidate = _best_candidate(
        _calibrate_merchant_candidates(_merchant_candidates(text), context)
    )
    time_candidate = _best_candidate(
        _calibrate_time_candidates(_time_candidates(text, timezone_name), context)
    )
    amount_cents = amount_candidate.amount_cents if amount_candidate else None
    merchant = merchant_candidate.value if merchant_candidate else None
    expense_time = time_candidate.value if time_candidate else None
    category_candidate = _best_candidate(
        _calibrate_category_candidates(
            _category_candidates(text, merchant), context, merchant_candidate
        )
    )
    category = category_candidate.category if category_candidate else None
    confidence = _estimate_confidence(
        context=context,
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

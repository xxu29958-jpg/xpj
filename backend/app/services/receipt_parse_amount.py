from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.services.receipt_parse_common import (
    _AmountCandidate,
    _best_candidate,
    _build_receipt_context,
    _is_before_payment_sheet,
    _is_payment_sheet_amount,
    _line_index_for_offset,
    _merge_dimensions,
    _nearby_text,
    _ReceiptContext,
    _ScoreDimensions,
)
from app.services.receipt_parse_rules import (
    AMOUNT_LABEL_SCORES,
    CLOCK_LINE_PATTERN,
    DISCOUNT_AMOUNT_LABELS,
    INLINE_AMOUNT_PATTERNS,
    LABELED_AMOUNT_PATTERN,
    MONEY_MARKERS,
    PRIMARY_AMOUNT_LINE_PATTERN,
    TRANSACTION_SUCCESS_KEYWORDS,
    UPPER_MONEY_MARKERS,
)


def _extract_amount_cents(text: str) -> int | None:
    context = _build_receipt_context(text)
    candidate = _best_candidate(
        _calibrate_amount_candidates(_amount_candidates(text), context)
    )
    return candidate.amount_cents if candidate else None


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
            line_text = lines[index].strip() if 0 <= index < len(lines) else ""
            has_nearby_success = _has_nearby_success(lines, index)
            evidence = [source, f"line:{line_text}"]
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
                candidates.append(
                    _AmountCandidate(
                        cents, score, index, source, dimensions.evidence, dimensions
                    )
                )

    return _apply_amount_cross_evidence(candidates)


def _calibrate_amount_candidates(
    candidates: list[_AmountCandidate], context: _ReceiptContext
) -> list[_AmountCandidate]:
    has_signed_primary_near_success = any(
        candidate.source == "line"
        and any("signed_primary_amount" in evidence for evidence in candidate.evidence)
        and any(
            "near_transaction_success" in evidence for evidence in candidate.evidence
        )
        for candidate in candidates
    )

    calibrated: list[_AmountCandidate] = []
    for candidate in candidates:
        profile = 0
        context_score = 0
        structure = 0
        noise = 0
        evidence: list[str] = []

        if context.profile == "alipay_bill_detail":
            if candidate.source == "line" and any(
                "signed_primary_amount" in item for item in candidate.evidence
            ):
                profile += 14
                evidence.append("profile_alipay_detail_primary:+14")
            if candidate.source == "label:订单金额" and has_signed_primary_near_success:
                noise -= 28
                evidence.append("profile_alipay_detail_order_amount:-28")
        elif context.profile == "alipay_success_page":
            if candidate.source in {"line", "currency"} and any(
                "near_transaction_success" in item for item in candidate.evidence
            ):
                profile += 10
                evidence.append("profile_alipay_success_amount:+10")
        elif context.profile == "bank_reminder":
            nearby_text = _nearby_text(
                context.lines, candidate.line_index, before=1, after=1
            )
            if candidate.source.startswith("label:交易金额") or any(
                marker in nearby_text for marker in ["支出人民币", "动账提醒"]
            ):
                profile += 12
                evidence.append("profile_bank_transaction_amount:+12")
                if "支出人民币" in nearby_text:
                    context_score += 18
                    evidence.append("bank_spend_sentence:+18")
        elif context.profile == "taobao_flash_payment":
            if _is_payment_sheet_amount(context, candidate):
                profile += 18
                structure += 58
                evidence.append("payment_sheet_primary_amount:+76")
            elif _is_before_payment_sheet(context, candidate.line_index):
                noise -= 18
                evidence.append("payment_sheet_product_area_amount:-18")
        elif context.profile == "mobility_payment":
            if candidate.source in {"yuan", "currency"}:
                structure += 8
                evidence.append("profile_mobility_inline_amount:+8")

        if _looks_like_status_bar_numeric_amount(context, candidate):
            noise -= 90
            evidence.append("status_bar_numeric_amount_noise:-90")

        if profile == 0 and context_score == 0 and structure == 0 and noise == 0:
            calibrated.append(candidate)
            continue

        dimensions = _merge_dimensions(
            candidate.dimensions,
            context=context_score,
            profile=profile,
            structure=structure,
            noise=noise,
            evidence=tuple(evidence),
        )
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


def _apply_amount_cross_evidence(
    candidates: list[_AmountCandidate],
) -> list[_AmountCandidate]:
    counts: dict[int, int] = {}
    sources: dict[int, set[str]] = {}
    for candidate in candidates:
        counts[candidate.amount_cents] = counts.get(candidate.amount_cents, 0) + 1
        sources.setdefault(candidate.amount_cents, set()).add(candidate.source)

    boosted: list[_AmountCandidate] = []
    for candidate in candidates:
        support = min(
            16,
            max(0, counts[candidate.amount_cents] - 1) * 6
            + max(0, len(sources[candidate.amount_cents]) - 1) * 4,
        )
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


def _has_nearby_success(lines: list[str], index: int) -> bool:
    nearby = "\n".join(lines[max(0, index - 2) : min(len(lines), index + 3)])
    return any(keyword in nearby for keyword in TRANSACTION_SUCCESS_KEYWORDS)


def _has_discount_context(lines: list[str], index: int) -> bool:
    nearby = "\n".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
    return any(label in nearby for label in DISCOUNT_AMOUNT_LABELS)


def _has_money_marker(value: str) -> bool:
    upper_value = value.upper()
    return any(marker in value for marker in MONEY_MARKERS) or any(
        marker in upper_value for marker in UPPER_MONEY_MARKERS
    )


def _looks_like_status_bar_numeric_amount(
    context: _ReceiptContext, candidate: _AmountCandidate
) -> bool:
    if candidate.source != "line" or candidate.line_index > 4:
        return False
    if any(
        "money_marker" in item or "signed_primary_amount" in item
        for item in candidate.evidence
    ):
        return False

    line_text = (
        context.lines[candidate.line_index].strip()
        if candidate.line_index < len(context.lines)
        else ""
    )
    if not re.fullmatch(r"\d{1,3}", line_text):
        return False

    nearby = _nearby_text(
        context.lines, candidate.line_index, before=2, after=1
    ).upper()
    has_network_marker = any(
        marker in nearby for marker in ("4G", "5G", "WIFI", "WI-FI", "VPN")
    )
    has_clock_marker = any(
        CLOCK_LINE_PATTERN.match(line.strip())
        for line in context.lines[: candidate.line_index + 1]
    )
    return has_network_marker or has_clock_marker


def _money_to_cents(value: str) -> int | None:
    try:
        amount = Decimal(value.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    cents = (amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)

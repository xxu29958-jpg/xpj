from __future__ import annotations

import re

from app.services.receipt_parse_common import (
    _best_candidate,
    _build_receipt_context,
    _line_index_for_offset,
    _MerchantCandidate,
    _merge_dimensions,
    _ReceiptContext,
    _ScoreDimensions,
)
from app.services.receipt_parse_rules import (
    BANK_KEYWORDS,
    CLOCK_LINE_PATTERN,
    MERCHANT_IGNORED_LINES,
    MERCHANT_KEYWORDS,
    MERCHANT_LABEL_PATTERN,
    MERCHANT_LABEL_SCORES,
    MERCHANT_NOISE_SUBSTRINGS,
    MERCHANT_REJECT_SUBSTRINGS,
    PAYMENT_METHOD_LINE_PATTERN,
    PAYMENT_SHEET_MERCHANT_MARKERS,
    PRIMARY_AMOUNT_LINE_PATTERN,
    SUCCESS_PAGE_AD_KEYWORDS,
    SUCCESS_PAGE_SKIP_LINES,
    TRANSACTION_SUCCESS_KEYWORDS,
)


def _extract_merchant(text: str) -> str | None:
    context = _build_receipt_context(text)
    candidate = _best_candidate(
        _calibrate_merchant_candidates(_merchant_candidates(text), context)
    )
    return candidate.value if candidate else None


def _merchant_candidates(text: str) -> list[_MerchantCandidate]:  # noqa: C901 - merchant-name scoring heuristic; branches enumerate domain signals (length, position, blacklist), splitting flattens not simplifies
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

    for index, line in enumerate(lines):
        if not any(marker in line for marker in PAYMENT_SHEET_MERCHANT_MARKERS):
            continue
        candidate = _score_merchant_candidate(
            text=text,
            value=_clean_merchant(line),
            base_score=102,
            line_index=index,
            source="payment_sheet_title",
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
            line_index=_line_index_for_offset(
                lower_text, lower_text.find(keyword.lower())
            ),
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


_INSTITUTION_LABEL_KEYWORDS: tuple[str, ...] = ("收单机构", "清算机构", "收款方全称")


def _score_bank_reminder(c: _MerchantCandidate, _ctx: _ReceiptContext) -> tuple[int, int, int, list[str]]:
    if c.value in BANK_KEYWORDS and c.source in {"keyword", "first_line"}:
        return 22, 0, 0, ["profile_bank_first_party:+22"]
    return 0, 0, 0, []


def _score_alipay_bill_detail(c: _MerchantCandidate, ctx: _ReceiptContext) -> tuple[int, int, int, list[str]]:
    profile = 0
    noise = 0
    evidence: list[str] = []
    if c.source == "success_title":
        profile += 16
        evidence.append("profile_alipay_detail_success_title:+16")
        if _has_more_specific_nearby_merchant_alias(ctx, c):
            noise -= 14
            evidence.append("short_alias_near_specific_merchant:-14")
    if c.source.startswith("label:收款方") or (
        c.source in {"keyword", "first_line"} and c.value in BANK_KEYWORDS
    ):
        noise -= 28
        evidence.append("profile_alipay_detail_institution_noise:-28")
    return profile, 0, noise, evidence


def _score_alipay_success_page(c: _MerchantCandidate, _ctx: _ReceiptContext) -> tuple[int, int, int, list[str]]:
    profile = 0
    noise = 0
    evidence: list[str] = []
    if c.source == "success_body":
        profile += 18
        evidence.append("profile_alipay_success_body:+18")
    if c.value in {"高德", "支付宝"}:
        noise -= 20
        evidence.append("profile_alipay_success_ad_platform:-20")
    return profile, 0, noise, evidence


def _score_wechat_payment_detail(c: _MerchantCandidate, _ctx: _ReceiptContext) -> tuple[int, int, int, list[str]]:
    profile = 0
    noise = 0
    evidence: list[str] = []
    if c.source == "payment_method_previous_line":
        profile += 16
        evidence.append("profile_wechat_payment_previous_line:+16")
    if c.value in {"微信支付", "支付服务"}:
        noise -= 28
        evidence.append("profile_wechat_platform_noise:-28")
    return profile, 0, noise, evidence


def _score_mobility_payment(c: _MerchantCandidate, _ctx: _ReceiptContext) -> tuple[int, int, int, list[str]]:
    if c.value == "高德" or "打车" in c.value:
        return 18, 0, 0, ["profile_mobility_provider:+18"]
    return 0, 0, 0, []


def _score_taobao_flash_payment(c: _MerchantCandidate, _ctx: _ReceiptContext) -> tuple[int, int, int, list[str]]:
    profile = 0
    structure = 0
    noise = 0
    evidence: list[str] = []
    if c.source == "payment_sheet_title":
        profile += 24
        structure += 18
        evidence.append("profile_payment_sheet_title:+42")
    if c.source.startswith("label:店铺") and any(
        noise_word in c.value for noise_word in MERCHANT_NOISE_SUBSTRINGS
    ):
        noise -= 70
        evidence.append("profile_payment_sheet_store_activity_noise:-70")
    return profile, structure, noise, evidence


_PROFILE_SCORERS = {
    "bank_reminder": _score_bank_reminder,
    "alipay_bill_detail": _score_alipay_bill_detail,
    "alipay_success_page": _score_alipay_success_page,
    "wechat_payment_detail": _score_wechat_payment_detail,
    "mobility_payment": _score_mobility_payment,
    "taobao_flash_payment": _score_taobao_flash_payment,
}


def _institution_noise(value: str) -> tuple[int, list[str]]:
    lowered = value.lower()
    if any(kw.lower() in lowered for kw in _INSTITUTION_LABEL_KEYWORDS):
        return -18, ["institution_label_noise:-18"]
    return 0, []


def _calibrate_one(candidate: _MerchantCandidate, context: _ReceiptContext) -> _MerchantCandidate:
    scorer = _PROFILE_SCORERS.get(context.profile)
    if scorer is None:
        profile, structure, noise, evidence = 0, 0, 0, []
    else:
        profile, structure, noise, evidence = scorer(candidate, context)

    inst_delta, inst_evidence = _institution_noise(candidate.value)
    noise += inst_delta
    evidence.extend(inst_evidence)

    if profile == 0 and structure == 0 and noise == 0:
        return candidate

    dimensions = _merge_dimensions(
        candidate.dimensions,
        profile=profile,
        structure=structure,
        noise=noise,
        evidence=tuple(evidence),
    )
    return _MerchantCandidate(
        value=candidate.value,
        score=dimensions.total,
        line_index=candidate.line_index,
        source=candidate.source,
        evidence=dimensions.evidence,
        dimensions=dimensions,
    )


def _calibrate_merchant_candidates(
    candidates: list[_MerchantCandidate], context: _ReceiptContext
) -> list[_MerchantCandidate]:
    return [_calibrate_one(candidate, context) for candidate in candidates]


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
    if source != "keyword" and any(
        keyword in value for keyword in SUCCESS_PAGE_AD_KEYWORDS
    ):
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
    return _MerchantCandidate(
        value=value,
        score=score,
        line_index=line_index,
        source=source,
        evidence=dimensions.evidence,
        dimensions=dimensions,
    )


def _merchant_source_score(source: str, base_score: int) -> int:
    if source == "success_title":
        return 72
    if source == "success_body":
        return 58
    if source == "payment_method_previous_line":
        return 54
    if source == "payment_sheet_title":
        return 66
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
    if any(
        keyword.lower() in lower_value
        for keyword in [
            "超市",
            "便利店",
            "外卖",
            "零食",
            "小吃",
            "餐",
            "打车",
            "闪购",
            "商户",
        ]
    ):
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
    if (
        CLOCK_LINE_PATTERN.match(value)
        or "4G" in upper_value
        or "5G" in upper_value
        or "WIFI" in upper_value
    ):
        return False
    return not any(label in value for label in MERCHANT_REJECT_SUBSTRINGS)


def _looks_like_payment_institution_context(text: str, keyword: str) -> bool:
    if keyword not in text:
        return False
    if "交易提醒" in text and text.splitlines()[0].strip() == keyword:
        return False
    return any(label in text for label in ["收单机构", "清算机构", "收款方全称"])


def _looks_like_bank_reminder(text: str, keyword: str) -> bool:
    lines = text.splitlines()
    return (
        keyword in BANK_KEYWORDS
        and bool(lines)
        and lines[0].strip() == keyword
        and "交易提醒" in text
    )


def _has_more_specific_nearby_merchant_alias(
    context: _ReceiptContext, candidate: _MerchantCandidate
) -> bool:
    value = candidate.value.strip()
    if len(value) >= 6:
        return False

    for line in context.lines[
        max(0, candidate.line_index - 1) : min(
            len(context.lines), candidate.line_index + 3
        )
    ]:
        cleaned = _clean_merchant(line)
        if not cleaned or cleaned == value:
            continue
        if value in cleaned and _is_title_merchant_candidate(cleaned):
            return True
    return False


def _clean_merchant(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" ：:，,。；;")
    return cleaned or None

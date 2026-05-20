from __future__ import annotations

from app.services.category_service import normalize_category
from app.services.receipt_parse_merchant import (
    _calibrate_merchant_candidates,
    _merchant_candidates,
)
from app.services.receipt_parse_rules import CATEGORY_HINT_RULES
from app.services.receipt_parse_common import (
    _CategoryCandidate,
    _MerchantCandidate,
    _ReceiptContext,
    _ScoreDimensions,
    _best_candidate,
    _build_receipt_context,
    _merge_dimensions,
)


def _suggest_category(text: str, merchant: str | None) -> str | None:
    context = _build_receipt_context(text)
    merchant_candidate = _best_candidate(
        _calibrate_merchant_candidates(_merchant_candidates(text), context)
    )
    candidate = _best_candidate(
        _calibrate_category_candidates(
            _category_candidates(text, merchant), context, merchant_candidate
        )
    )
    return candidate.category if candidate else None


def _category_candidates(text: str, merchant: str | None) -> list[_CategoryCandidate]:
    merchant_text = (merchant or "").lower()
    full_text = f"{merchant or ''}\n{text}".lower()
    buckets: dict[str, _CategoryCandidate] = {}

    def add_candidate(
        rule_index: int, category: str, score: int, source: str, evidence: str
    ) -> None:
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
                add_candidate(
                    rule_index,
                    rule.category,
                    88,
                    "merchant_keyword",
                    f"merchant:{keyword}",
                )
            elif lowered in full_text:
                add_candidate(
                    rule_index, rule.category, 42, "text_keyword", f"text:{keyword}"
                )

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

        if merchant_value and any(
            item.startswith("merchant:") for item in candidate.evidence
        ):
            consistency += 10
            evidence.append("merchant_category_alignment:+10")
        if context.profile == "mobility_payment" and candidate.category == "交通":
            profile += 16
            evidence.append("profile_mobility_transport:+16")
        if (
            context.profile == "alipay_success_page"
            and candidate.category == "交通"
            and merchant_value != "高德"
        ):
            noise -= 20
            evidence.append("profile_alipay_ad_transport_noise:-20")

        if profile == 0 and consistency == 0 and noise == 0:
            calibrated.append(candidate)
            continue

        dimensions = _merge_dimensions(
            candidate.dimensions,
            profile=profile,
            consistency=consistency,
            noise=noise,
            evidence=tuple(evidence),
        )
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

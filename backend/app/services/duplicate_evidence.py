"""Deterministic duplicate admission; image similarity is recall, never a financial verdict."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta

from app.models import Expense, OcrFact
from app.services.time_service import ensure_utc

ALGORITHM_VERSION = "duplicate-evidence-v2"
_TRANSACTION_ID = re.compile(
    r"(?:交易单号|交易号|支付单号|流水号)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9-]{5,63})(?![A-Za-z0-9*×-])")
_NON_EXPENSE = {"repayment_receipt", "refund_receipt", "income_receipt",
    "conflicting_transaction_kinds", "transaction_not_completed"}


@dataclass(frozen=True)
class DuplicateCandidateScore:
    candidate_id: int
    score: float
    reasons: tuple[str, ...] = ()
    algorithm_version: str = ALGORITHM_VERSION


def normalised_merchant(value: str | None) -> str:
    return (value or "").strip().casefold()


def phash_distance(left: str | None, right: str | None) -> int:
    if not left or not right:
        return 64
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 64


def _money(expense: Expense) -> tuple[str | None, int | None]:
    # Compare original units, never two converted home totals at different rates.
    code = expense.original_currency_code
    amount = expense.original_amount_minor
    if amount is None and code == expense.home_currency_code:
        amount = expense.amount_cents
    return code, amount


def _identifiers(expense: Expense, fact: OcrFact | None) -> tuple[str | None, set[str]]:
    text = fact.raw_text if fact else ""
    providers = [name for name, label in (("alipay", "支付宝"), ("wechat", "微信"))
        if label in text or label in (expense.source or "") or expense.source == name]
    merchant = normalised_merchant(expense.merchant)
    namespace = providers[0] if len(providers) == 1 else f"merchant:{merchant}" if not providers and merchant else None
    return namespace, {match[1] for match in _TRANSACTION_ID.finditer(text)}


def _source_conflict(expense: Expense, fact: OcrFact | None) -> bool:
    if expense.source == "bill_split_received":
        return True  # A received split is a separate obligation, not a second capture.
    if expense.status != "pending" or fact is None or not fact.evidence_json:
        return False
    evidence = json.loads(fact.evidence_json).get("field_parse", {})
    return any(item["field"] == "amount_cents" and item["reason"] in _NON_EXPENSE
        for item in evidence.get("decisions", ()))


def _time_relation(left: Expense, right: Expense) -> str | None:
    left_time, right_time = ensure_utc(left.expense_time), ensure_utc(right.expense_time)
    if left_time is not None and right_time is not None:
        delta = abs(left_time - right_time)
        if delta > timedelta(hours=24):
            return "conflict"
        return "time_within_1h" if delta <= timedelta(hours=1) else "time_within_24h"
    if (left.time_precision == right.time_precision == "date_only"
            and left.user_local_date is not None and right.user_local_date is not None
            and left.source_timezone == right.source_timezone):
        return "same_transaction_date" if left.user_local_date == right.user_local_date else "conflict"
    return None  # Receipt/confirmation clocks and missing precision are not transaction evidence.


def compare_duplicate_evidence(expense: Expense, candidate: Expense, *,
        expense_fact: OcrFact | None, candidate_fact: OcrFact | None) -> DuplicateCandidateScore | None:
    if (expense.id == candidate.id or expense.tenant_id != candidate.tenant_id
            or expense.status == "rejected" or candidate.status == "rejected"
            or _source_conflict(expense, expense_fact) or _source_conflict(candidate, candidate_fact)):
        return None
    money_relation = _money_relation(expense, candidate)
    id_relation = _identifier_relation(expense, candidate, expense_fact, candidate_fact)
    time_reason = _time_relation(expense, candidate)
    if "conflict" in (money_relation, id_relation, time_reason):
        return None
    reasons = _duplicate_reasons(expense, candidate, money_relation, id_relation, time_reason)
    if reasons is None:
        return None
    weights = {"transaction_id_match": 0.5, "image_hash_match": 0.2, "image_perceptual_hash_match": 0.1,
        "amount_match": 0.3, "merchant_match": 0.15, "time_within_1h": 0.15,
        "time_within_24h": 0.05, "same_transaction_date": 0.05, "transaction_evidence_incomplete": 0}
    score = min(1.0, sum(weights[reason] for reason in reasons))
    return DuplicateCandidateScore(candidate.id, round(score, 4), tuple(reasons))


def _money_relation(expense: Expense, candidate: Expense) -> str:
    code, amount = _money(expense)
    other_code, other_amount = _money(candidate)
    if code and other_code and code != other_code:
        return "conflict"
    if amount is not None and other_amount is not None and code == other_code:
        if amount != other_amount:
            return "conflict"
        if code:
            return "match"
    return "unknown"


def _identifier_relation(expense, candidate, expense_fact, candidate_fact) -> str:
    namespace, identifiers = _identifiers(expense, expense_fact)
    other_namespace, other_identifiers = _identifiers(candidate, candidate_fact)
    comparable_ids = bool(namespace and namespace == other_namespace and identifiers and other_identifiers)
    if comparable_ids and (len(identifiers) != 1 or identifiers != other_identifiers):
        return "conflict"
    return "match" if comparable_ids else "unknown"


def _duplicate_reasons(expense, candidate, money_relation, id_relation, time_reason):
    image_equal = bool(expense.image_hash and expense.image_hash == candidate.image_hash)
    image_near = phash_distance(expense.image_perceptual_hash, candidate.image_perceptual_hash) <= 5
    amount_equal = money_relation == "match"
    comparable_ids = id_relation == "match"
    merchant_equal = bool(normalised_merchant(expense.merchant)
        and normalised_merchant(expense.merchant) == normalised_merchant(candidate.merchant))
    transaction_match = comparable_ids or (amount_equal and merchant_equal and time_reason)
    if not (image_equal or image_near or transaction_match):
        return None
    # Rank evidence strength, not a calibrated probability. Compatible transaction
    # fields outrank image-only recall so a first visual hit cannot hide stronger matches.
    evidence = [("transaction_id_match", comparable_ids), ("image_hash_match", image_equal),
        ("image_perceptual_hash_match", image_near and not image_equal),
        ("amount_match", amount_equal), ("merchant_match", merchant_equal), (time_reason, bool(time_reason))]
    reasons = [reason for reason, matched in evidence if matched]
    if not transaction_match:
        reasons.append("transaction_evidence_incomplete")
    return reasons


def duplicate_reason(match: DuplicateCandidateScore) -> str:
    labels = {"transaction_id_match": "交易标识相同", "image_hash_match": "原件完全一致",
        "image_perceptual_hash_match": "原件内容近似", "amount_match": "原币金额相同",
        "merchant_match": "商家相同", "time_within_1h": "交易时间在一小时内",
        "time_within_24h": "交易时间在一天内", "same_transaction_date": "交易日期相同",
        "transaction_evidence_incomplete": "交易信息不足，需对照原件核实"}
    return "；".join(labels[reason] for reason in match.reasons)

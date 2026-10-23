"""Publish existing field evidence and reject conflicting top-ranked values."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime

from app.services.receipt_parse_amount_roles import AMOUNT_ROLE_PRIORITY
from app.services.receipt_parse_common import (
    FIELD_PARSE_VERSION,
    ReceiptFieldCandidate,
    ReceiptFieldDecision,
    _AmountCandidate,
    _CandidateT,
    _MerchantCandidate,
    _TimeCandidate,
)
from app.services.receipt_parse_time import NON_TRANSACTION_TIME_ROLES, compatible_times


def raw_line_spans(raw_text: str) -> tuple[tuple[int, int], ...]:
    spans = []
    offset = 0
    for line in raw_text.splitlines(keepends=True):
        if line.strip():
            spans.append((offset + len(line) - len(line.lstrip()), offset + len(line.rstrip())))
        offset += len(line)
    return tuple(spans)


def evidence_block_spans(raw_text: str, blocks: Sequence[dict] | None) -> tuple[tuple[int, int, int], ...]:
    """Use block positions only when their actual joined text is the parser input."""
    texts = [(index, block["text"].strip()) for index, block in enumerate(blocks or ()) if block["text"].strip()]
    if "\n".join(text for _, text in texts) != raw_text:
        return ()
    spans = []
    offset = 0
    for index, text in texts:
        spans.append((index, offset, offset + len(text)))
        offset += len(text) + 1
    return tuple(spans)


def _original_spans(lines: tuple[tuple[int, int], ...], spans: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    # Normalized offsets are converted once for both amount and time evidence.
    positions = []
    for raw_start, raw_end in lines:
        positions.extend(range(raw_start, raw_end))
        positions.append(raw_end)
    return tuple((positions[left], positions[right - 1] + 1) for left, right in sorted(spans))


def _candidate_spans(raw_text: str, field: str, candidate) -> tuple[tuple[int, int], ...]:
    if field == "category":
        # Category's legacy line_index is a rule index, not an OCR line number.
        terms = [item.partition(":")[2] for item in candidate.evidence if item.startswith(("text:", "merchant:"))]
        return tuple(sorted({match.span() for term in terms for match in re.finditer(re.escape(term), raw_text, re.I)}))
    lines = raw_line_spans(raw_text)
    if isinstance(candidate, (_TimeCandidate, _AmountCandidate, _MerchantCandidate)) and candidate.normalized_span is not None:
        # The parser normalizes blank lines/CRLF, but published offsets always
        # address the immutable original text (including all original whitespace).
        start, end = candidate.normalized_span
        spans = [(start, end)]
        if (label_span := getattr(candidate, "label_span", None)) is not None:
            spans.append(label_span)
        spans.extend(getattr(candidate, "context_spans", ()))
        return _original_spans(lines, spans)
    start, end = lines[candidate.line_index]
    if field == "amount_cents" and candidate.source.startswith("label:"):
        label = candidate.source.partition(":")[2]
        tail = raw_text[start:end].partition(label)[2].strip(" :：")
        if not tail and candidate.line_index + 1 < len(lines):
            end = lines[candidate.line_index + 1][1]
    elif field == "expense_time" and candidate.evidence:
        line_count = len(candidate.evidence[0].splitlines())
        end = lines[min(candidate.line_index + line_count - 1, len(lines) - 1)][1]
    return ((start, end),)


def _public_candidate(raw_text: str, field: str, candidate: _CandidateT,
        block_spans: tuple[tuple[int, int, int], ...], currency_code: str | None,
        minor_unit_exponent: int | None) -> ReceiptFieldCandidate:
    attribute = {"amount_cents": "amount_cents", "category": "category"}.get(field, "value")
    value = getattr(candidate, attribute)
    if isinstance(value, datetime):
        value = value.isoformat()
    spans = _candidate_spans(raw_text, field, candidate)
    block_indices = tuple(index for index, start, end in block_spans
        if any(start < raw_end and raw_start < end for raw_start, raw_end in spans))
    semantic_fields = {name: getattr(candidate, name) for name in (
        "role", "precision", "local_value", "timezone_name", "timezone_basis",
        "utc_offset_seconds", "inferred_components", "reference_time", "review_reason", "components",
    )} if isinstance(candidate, _TimeCandidate) else {}
    if isinstance(candidate, _AmountCandidate):
        semantic_fields = {"role": candidate.role, "review_reason": candidate.review_reason}
    if isinstance(candidate, _MerchantCandidate):
        semantic_fields = {"role": candidate.role}
    identity = json.dumps([FIELD_PARSE_VERSION, field, value, candidate.source, spans,
        currency_code, minor_unit_exponent, semantic_fields], ensure_ascii=False, separators=(",", ":"))
    return ReceiptFieldCandidate(
        id=hashlib.sha256(identity.encode()).hexdigest(), field=field, value=value,
        rank_score=candidate.score, source=candidate.source, raw_spans=spans,
        block_indices=block_indices, reasons=candidate.evidence,
        currency_code=currency_code, minor_unit_exponent=minor_unit_exponent,
        **semantic_fields,
    )


def resolve_field(
    raw_text: str,
    field: str,
    candidates: list[_CandidateT],
    *,
    block_spans: tuple[tuple[int, int, int], ...] = (),
    currency_code: str | None = None,
    minor_unit_exponent: int | None = None,
) -> tuple[_CandidateT | None, tuple[ReceiptFieldCandidate, ...], ReceiptFieldDecision]:
    precision_order = {"second": 0, "minute": 1, "date_only": 2}
    ordered = sorted(candidates, key=lambda item: (
        -int(field == "merchant" and getattr(item, "role", "") == "merchant"),
        -item.score, precision_order.get(getattr(item, "precision", ""), 0), item.line_index,
    ))
    public = tuple(_public_candidate(raw_text, field, item, block_spans, currency_code, minor_unit_exponent)
        for item in ordered)
    if not public:
        return None, public, ReceiptFieldDecision(field, "missing", None, "no_candidate")
    if field == "amount_cents":
        selected, decision = _resolve_amount(ordered, public)
        return selected, public, decision
    if field == "expense_time":
        selected, decision = _resolve_time(ordered, public)
        return selected, public, decision
    top_values = {item.value for item in public if item.rank_score == public[0].rank_score
        and (field != "merchant" or item.role == public[0].role)}
    if len(top_values) != 1:
        return None, public, ReceiptFieldDecision(field, "ambiguous", None, "conflicting_top_values")
    return ordered[0], public, ReceiptFieldDecision(field, "selected", public[0].id, "unique_top_value")


def _resolve_time(candidates: list[_CandidateT], public: tuple[ReceiptFieldCandidate, ...]
        ) -> tuple[_CandidateT | None, ReceiptFieldDecision]:
    top = [item for item in candidates if item.score == candidates[0].score]
    if top[0].role in NON_TRANSACTION_TIME_ROLES:
        return None, ReceiptFieldDecision("expense_time", "needs_review", None, "non_transaction_time")
    if any(not compatible_times(left, right) for index, left in enumerate(top) for right in top[index + 1:]):
        return None, ReceiptFieldDecision("expense_time", "ambiguous", None, "conflicting_transaction_times")
    if top[0].review_reason:
        return None, ReceiptFieldDecision("expense_time", "needs_review", None, top[0].review_reason)
    return top[0], ReceiptFieldDecision("expense_time", "selected", public[0].id, "compatible_transaction_time")


def _resolve_amount(candidates: list[_CandidateT], public: tuple[ReceiptFieldCandidate, ...]
        ) -> tuple[_CandidateT | None, ReceiptFieldDecision]:
    leaders = _amount_leaders(public)
    if not leaders:
        reason = next((item.review_reason for item in public if item.review_reason), "non_expense_amount")
        return None, ReceiptFieldDecision("amount_cents", "needs_review", None, reason)
    if len({public[index].value for index in leaders}) != 1:
        return None, ReceiptFieldDecision("amount_cents", "ambiguous", None, "conflicting_transaction_amounts")
    winner = leaders[0]
    return candidates[winner], ReceiptFieldDecision("amount_cents", "selected", public[winner].id, "amount_role_and_value")


def _amount_leaders(public: tuple[ReceiptFieldCandidate, ...]) -> list[int]:
    priorities = {index: AMOUNT_ROLE_PRIORITY[item.role] for index, item in enumerate(public)
        if item.role in AMOUNT_ROLE_PRIORITY and item.rank_score > 0 and not item.review_reason}
    priority = max(priorities.values(), default=-1)
    leaders = [index for index, value in priorities.items() if value == priority]
    if priority == 0:
        leaders = [index for index in leaders if public[index].rank_score == public[leaders[0]].rank_score]
    return leaders

"""Bounded transaction-card interpretations using the same field vocabulary."""

import re

from app.services.receipt_parse_merchant import _is_title_merchant_candidate
from app.services.receipt_parse_rules import (
    INLINE_AMOUNT_PATTERNS,
    TRANSACTION_SUCCESS_KEYWORDS,
    is_primary_amount_line,
    iter_labeled_amount_matches,
    iter_labeled_merchant_matches,
)


def _amount_prefix_start(lines: list[tuple[int, int, str]], index: int, lower: int) -> int | None:
    first = max(lower, index - 2)
    texts = [line[2] for line in lines[first:index]]
    if not texts:
        return None
    last_line = sum(len(text) + 1 for text in texts[:-1])
    matches = [match for match in iter_labeled_amount_matches(texts)
        if match.normalized_span[1] > last_line]
    if matches:
        return first + min(match.line_index for match in matches)
    return index - 1 if is_primary_amount_line(texts[-1]) else None


def _merchant_prefix_start(lines: list[tuple[int, int, str]], index: int, lower: int) -> int:
    first = max(lower, index - 2)
    texts = [line[2] for line in lines[first:index]]
    if not texts:
        return index
    last_line = sum(len(text) + 1 for text in texts[:-1])
    matches = [match for match in iter_labeled_merchant_matches(texts) if match.value_span[0] >= last_line]
    if matches:
        return first + min(match.line_index for match in matches)
    return index - 1 if _is_title_merchant_candidate(texts[-1]) else index


def _card_start(lines: list[tuple[int, int, str]], index: int, lower: int, message_list: bool) -> int:

    start = index
    amount_start = _amount_prefix_start(lines, index, lower)
    if amount_start is not None:
        start = _merchant_prefix_start(lines, amount_start, lower)
    elif message_list:
        while start > max(lower, index - 3) and not re.search(r"联系收款方|查看详情|付款方式", lines[start - 1][2]):
            start -= 1
    return lines[start][0]


def _card_has_amount(card: str) -> bool:

    lines = card.splitlines()
    return (any(is_primary_amount_line(line) for line in lines) or bool(iter_labeled_amount_matches(lines))
        or any(pattern.search(card) for pattern, _, _ in INLINE_AMOUNT_PATTERNS))


def transaction_event_spans(raw_text: str) -> tuple[tuple[int, int], ...]:
    """Separate repeated cards, retaining the merchant/amount prefix of a success status."""

    lines = [(match.start(), match.end(), match.group().strip())
             for match in re.finditer(r"[^\r\n]+", raw_text) if match.group().strip()]
    headings = {*TRANSACTION_SUCCESS_KEYWORDS, "交易提醒"}
    anchors = [index for index, (_, _, text) in enumerate(lines) if text in headings]
    if len(anchors) < 2:
        return ()
    # Separate success toasts alone are not sufficient: each card needs money.
    spans = []
    message_list = "服务消息" in raw_text or "支付消息" in raw_text
    starts = []
    # One look-ahead boundary prevents the twentieth card from absorbing an unparsed tail.
    for number, index in enumerate(anchors[:21]):
        lower = anchors[number - 1] + 1 if number else 0
        starts.append(_card_start(lines, index, lower, message_list))
    for number, start in enumerate(starts[:20]):
        end = starts[number + 1] if number + 1 < len(starts) else len(raw_text)
        card = raw_text[start:end]
        if _card_has_amount(card):
            spans.append((start, end))
    return tuple(spans) if len(spans) > 1 else ()

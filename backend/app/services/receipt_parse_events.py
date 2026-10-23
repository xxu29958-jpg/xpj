"""Bounded transaction-card interpretations using the same field vocabulary."""

import re

from app.services.receipt_parse_merchant import _is_title_merchant_candidate
from app.services.receipt_parse_rules import (
    TRANSACTION_SUCCESS_KEYWORDS,
    is_primary_amount_line,
    iter_labeled_amount_matches,
)


def _card_start(lines: list[tuple[int, int, str]], index: int, lower: int, message_list: bool) -> int:

    start = index
    if index > lower and _card_has_amount(lines[index - 1][2]):
        start = index - 1
        if start > lower and _is_title_merchant_candidate(lines[start - 1][2]):
            start -= 1
    elif message_list:
        while start > max(lower, index - 3) and not re.search(r"联系收款方|查看详情|付款方式", lines[start - 1][2]):
            start -= 1
    return lines[start][0]


def _card_has_amount(card: str) -> bool:

    lines = card.splitlines()
    return any(is_primary_amount_line(line) for line in lines) or bool(iter_labeled_amount_matches(lines))


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

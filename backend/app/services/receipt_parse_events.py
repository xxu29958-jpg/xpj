"""Independent transaction-card interpretations using the same field vocabulary."""

import re

from app.services.receipt_parse_amount_roles import _role
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
    texts = [line[2] for line in lines[lower:index]]
    if not texts:
        return index
    # Metadata between the merchant and amount belongs to this same prefix.
    # Inspect only this anchor interval; the nearest explicit merchant owns it.
    matches = iter_labeled_merchant_matches(texts)
    if matches:
        return lower + max(match.line_index for match in matches)
    return index - 1 if _is_title_merchant_candidate(texts[-1]) else index


def _card_start(lines: list[tuple[int, int, str]], index: int, lower: int, message_list: bool) -> int:
    # Notification shades put the app and clock before each transaction title.
    apps = [position for position in range(max(lower, index - 3), index)
        if re.match(r"^(?:支付宝|微信支付|微信)(?:[·•\s(（]|$)", lines[position][2])]
    if apps:
        return lines[apps[-1]][0]
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
    text = "\n".join(lines)
    spans = [match.normalized_span for match in iter_labeled_amount_matches(lines)]
    spans.extend(match.span() for pattern, _, _ in INLINE_AMOUNT_PATTERNS for match in pattern.finditer(text))
    offset = 0
    for line in lines:
        if is_primary_amount_line(line):
            spans.append((offset, offset + len(line)))
        offset += len(line) + 1
    # Share the field parser's semantic roles, not just its monetary vocabulary.
    return any(_role(text, start, end) in {"unknown", "payment", "expense", "total", "order",
        "repayment", "refund", "income", "topup"} for start, end in spans)


def _card_anchors(lines: list[tuple[int, int, str]]) -> list[int]:
    headings = {*TRANSACTION_SUCCESS_KEYWORDS, "交易提醒", "订单支付成功"}
    # A labelled status value describes the enclosing payment, not another card.
    status_labels = {"交易状态", "支付状态", "付款状态", "订单状态"}
    return [index for index, (_, _, text) in enumerate(lines) if (text in headings
        or re.match(r"^交易提醒(?:[\s:：]|你有一笔)", text)
        or re.search(r"卡\s*(?:充值金额|刷卡完成)[：:，,\s]", text))
        and (not index or lines[index - 1][2].rstrip(":： ") not in status_labels)]


def _notification_end(raw_text: str, start: int, end: int) -> int:
    """A second display clock belongs to the next notification, even when it is an ad."""
    lines = list(re.finditer(r"[^\r\n]+", raw_text[start:end]))
    clocks = [index for index, line in enumerate(lines)
        if re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", line.group().strip())]
    if len(clocks) > 1 and clocks[1] > 0:
        return start + lines[clocks[1] - 1].start()
    return end


def _card_starts(raw_text: str, lines: list[tuple[int, int, str]], anchors: list[int], message_list: bool) -> list[int]:
    """Bind app/merchant prefixes without taking the preceding card's amount."""
    first_start = _card_start(lines, anchors[0], 0, message_list)
    prefix_layout = first_start < lines[anchors[0]][0]
    starts = [first_start]
    for number, index in enumerate(anchors[1:], start=1):
        start = lines[index][0]
        prefix = _card_start(lines, index, anchors[number - 1] + 1, message_list)
        app_prefix = re.match(r"^(?:支付宝|微信支付|微信)(?:[·•\s(（]|$)", raw_text[prefix:])
        # Prefix ownership cannot remove the preceding card's only amount.
        if (prefix_layout or app_prefix) and _card_has_amount(raw_text[starts[-1]:prefix]):
            start = prefix
        starts.append(start)
    return starts


def transaction_event_spans(raw_text: str) -> tuple[tuple[int, int], ...]:
    """Separate repeated cards, retaining the merchant/amount prefix of a success status."""
    lines = [(match.start(), match.end(), match.group().strip())
             for match in re.finditer(r"[^\r\n]+", raw_text) if match.group().strip()]
    anchors = _card_anchors(lines)
    if len(anchors) < 2:
        return ()
    # Display clocks distinguish a notification shade from repeated receipt status labels.
    notification_shade = "交易提醒" in raw_text and len(re.findall(r"(?m)^\s*\d{1,2}:\d{2}\s*$", raw_text)) > 1
    starts = _card_starts(raw_text, lines, anchors, "服务消息" in raw_text or "支付消息" in raw_text)
    spans = []
    for number, start in enumerate(starts):
        end = starts[number + 1] if number + 1 < len(starts) else len(raw_text)
        if notification_shade:
            end = _notification_end(raw_text, start, end)
        card = raw_text[start:end]
        if _card_has_amount(card) or (notification_shade and "订单支付成功" in card):
            spans.append((start, end))
    return tuple(spans) if len(spans) > 1 else ()

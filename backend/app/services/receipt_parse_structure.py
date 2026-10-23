"""Small evidence relations shared by field parsing; no inferred financial facts."""

from __future__ import annotations

import re
from collections.abc import Sequence


def _bounds(points: Sequence) -> tuple[float, float, float, float]:
    xs, ys = zip(*points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def related_value_index(lines: Sequence[str], blocks: Sequence[dict] | None, index: int) -> int | None:
    """A label's nearest right-hand value, or its aligned value immediately below."""
    if not blocks:
        return index + 1 if index + 1 < len(lines) else None
    left, top, right, bottom = _bounds(blocks[index]["box"])
    height = max(1, bottom - top)
    choices = []
    for other, block in enumerate(blocks):
        if other == index:
            continue
        x, other_top, _, other_bottom = _bounds(block["box"])
        y = (other_top + other_bottom) / 2
        same_row = abs(y - (top + bottom) / 2) <= height * 0.6 and x >= right
        below = bottom <= other_top <= bottom + height * 1.8 and abs(x - left) <= height
        if same_row or below:
            choices.append(((0, x - right) if same_row else (1, y - bottom), other))
    return min(choices)[1] if choices else None


def promotion_start(text: str) -> int | None:
    match = re.search(r"^(?:活动专区|福利中心|推荐服务|支付奖励|猜你喜欢)\s*$", text, re.M)
    return match.start() if match else None


def transaction_event_spans(raw_text: str) -> tuple[tuple[int, int], ...]:
    """Repeated transaction-card headings require separate interpretations."""
    lines = [(match.start(), match.end(), match.group().strip())
             for match in re.finditer(r"[^\r\n]+", raw_text)]
    headings = {"交易提醒", "付款成功", "支付成功", "交易成功", "自动扣款成功"}
    anchors = [index for index, (_, _, text) in enumerate(lines) if text in headings]
    if len(anchors) < 2:
        return ()
    # Separate success toasts alone are not sufficient: each card needs money.
    spans = []
    message_list = "服务消息" in raw_text or "支付消息" in raw_text
    starts = []
    for index in anchors[:20]:
        start = index
        if message_list:
            while start > max(0, index - 3) and not re.search(r"联系收款方|查看详情|付款方式", lines[start - 1][2]):
                start -= 1
        starts.append(lines[start][0])
    for number, start in enumerate(starts):
        end = starts[number + 1] if number + 1 < len(starts) else len(raw_text)
        card = raw_text[start:end]
        if re.search(r"(?:[¥￥]\s*\d|\d(?:[.,]\d+)?\s*元|(?:支付|交易|付款)金额[:：\s]*\d)", card):
            spans.append((start, end))
    return tuple(spans) if len(spans) > 1 else ()

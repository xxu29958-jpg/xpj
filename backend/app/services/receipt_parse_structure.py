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

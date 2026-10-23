"""An explicit page heading can supply a scoped year, never an upload-time guess."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.receipt_parse_structure import _bounds

_HEADING = re.compile(r"(?:账单\s*)?(?P<year>\d{4})年\s*(?:(?P<month>\d{1,2})月)?\s*(?:账单|交易记录|交易明细|收支明细)?")


@dataclass(frozen=True)
class PageYearAnchor:
    year: int
    month: int | None
    span: tuple[int, int]


def _heading_distance(heading_index: int, date_index: int, blocks: Sequence[dict] | None) -> float | None:
    if not blocks:
        return date_index - heading_index if heading_index < date_index else None
    left, _, right, bottom = _bounds(blocks[heading_index]["box"])
    date_left, date_top, date_right, _ = _bounds(blocks[date_index]["box"])
    if bottom <= date_top and max(left, date_left) <= min(right, date_right):
        return date_top - bottom
    return None


def page_year_anchor(text: str, start: int, month: int, blocks: Sequence[dict] | None) -> PageYearAnchor | None:
    date_index = text.count("\n", 0, start)
    anchors = []
    offset = 0
    for index, line in enumerate(text.splitlines(keepends=True)):
        match = _HEADING.fullmatch(line.strip())
        distance = _heading_distance(index, date_index, blocks) if match else None
        if distance is not None:
            anchor = PageYearAnchor(int(match["year"]), int(match["month"]) if match["month"] else None,
                (offset, offset + len(line.rstrip())))
            anchors.append((distance, anchor))
        offset += len(line)
    if not anchors:
        return None
    anchors.sort(key=lambda item: item[0])
    closest = [anchor for distance, anchor in anchors if distance == anchors[0][0]]
    if len({(anchor.year, anchor.month) for anchor in closest}) != 1:
        return None
    anchor = closest[0]
    return anchor if anchor.month in {None, month} else None

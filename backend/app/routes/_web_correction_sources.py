"""Current-source guards for composite Web expense corrections.

The browser edits item and split rows that may be replaced concurrently by
another consumer.  These helpers bind submitted rows to the current public
identities before the correction adapter builds a replacement payload.
"""

from __future__ import annotations

from app.schemas import ExpenseItemRequest, ExpenseItemResponse, ExpenseSplitResponse


def _submitted_item_indexes(*fields: list[str]) -> list[int]:
    size = max(*(len(values) for values in fields), 0)
    return [
        index
        for index in range(size)
        if any(index < len(values) and values[index].strip() for values in fields)
    ]


def submitted_item_source_ids(
    item_public_id: list[str],
    *item_fields: list[str],
) -> list[str]:
    return [
        item_public_id[index].strip() if index < len(item_public_id) else ""
        for index in _submitted_item_indexes(*item_fields)
    ]


def item_sources_match_current(
    submitted_public_ids: list[str],
    current: list[ExpenseItemResponse],
) -> bool:
    submitted = [public_id.strip() for public_id in submitted_public_ids if public_id.strip()]
    if len(submitted) != len(set(submitted)):
        return False
    return set(submitted) == {item.public_id for item in current}


def split_sources_match_current(
    submitted_public_ids: list[str],
    current: list[ExpenseSplitResponse],
) -> bool:
    submitted = [public_id.strip() for public_id in submitted_public_ids if public_id.strip()]
    if len(submitted) != len(set(submitted)):
        return False
    return set(submitted) == {split.public_id for split in current}


def preserve_item_provenance(
    candidate: list[ExpenseItemRequest],
    current: list[ExpenseItemResponse],
    source_public_ids: list[str],
) -> list[ExpenseItemRequest]:
    current_by_public_id = {item.public_id: item for item in current}
    preserved: list[ExpenseItemRequest] = []
    used_sources: set[str] = set()
    for item, source_public_id in zip(candidate, source_public_ids, strict=True):
        source = current_by_public_id.get(source_public_id)
        if source is None or source_public_id in used_sources:
            preserved.append(item)
            continue
        used_sources.add(source_public_id)
        preserved.append(
            item.model_copy(update={"raw_text": source.raw_text, "confidence": source.confidence})
        )
    return preserved

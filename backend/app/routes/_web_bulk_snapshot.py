"""Parse browser bulk-selection snapshots without weakening row OCC."""

from __future__ import annotations

from app.routes.web_common import parse_form_row_version_token

BulkSnapshot = tuple[list[int], dict[int, int]]


def _normalize_snapshot(pairs: list[tuple[int, str]]) -> BulkSnapshot | None:
    unique_expense_ids: list[int] = []
    expected_by_id: dict[int, int] = {}
    for expense_id, raw_token in pairs:
        parsed = parse_form_row_version_token(raw_token)
        if expense_id <= 0 or parsed is None or parsed <= 0:
            return None
        previous = expected_by_id.get(expense_id)
        if previous is not None:
            if previous != parsed:
                return None
            continue
        unique_expense_ids.append(expense_id)
        expected_by_id[expense_id] = parsed
    return unique_expense_ids, expected_by_id


def _parse_encoded_snapshot(expense_snapshots: list[str]) -> BulkSnapshot | None:
    pairs: list[tuple[int, str]] = []
    for raw_snapshot in expense_snapshots:
        raw_id, separator, raw_token = raw_snapshot.partition(":")
        if not separator:
            return None
        try:
            expense_id = int(raw_id)
        except ValueError:
            return None
        pairs.append((expense_id, raw_token))
    return _normalize_snapshot(pairs)


def parse_bulk_snapshot(
    expense_ids: list[int],
    expected_row_versions: list[str],
    expense_snapshots: list[str],
) -> BulkSnapshot | None:
    """Reconcile JS parallel fields with native checkbox snapshots.

    The encoded ``id:row_version`` value makes the form usable without
    JavaScript. Progressive enhancement also submits the established parallel
    fields; if both representations are present they must be identical.
    """
    legacy_present = bool(expense_ids or expected_row_versions)
    encoded_present = bool(expense_snapshots)
    legacy = None
    if legacy_present:
        if len(expense_ids) != len(expected_row_versions):
            return None
        legacy = _normalize_snapshot(
            list(zip(expense_ids, expected_row_versions, strict=True))
        )
        if legacy is None:
            return None
    encoded = _parse_encoded_snapshot(expense_snapshots) if encoded_present else None
    if encoded_present and encoded is None:
        return None
    if legacy is not None and encoded is not None and legacy != encoded:
        return None
    return encoded or legacy or ([], {})

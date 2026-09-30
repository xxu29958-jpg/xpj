"""Explicit preparation of a retained correction against a freshly read fact; never writes."""
from __future__ import annotations

import json
from uuid import uuid4

from app.routes._web_accounting_time import TIME_FIELDS
from app.routes._web_correction_form import CorrectionFormData, correction_form_projection
from app.routes._web_correction_page import web_correction_context
from app.routes._web_correction_snapshot import ITEM_FIELDS, SPLIT_FIELDS, original_correction_basis, raw_string
from app.routes.web_common import templates


def _row_values(rows: list[dict], fields: dict) -> list[dict]:
    return [{key: raw_string(row.get(key)) for key in fields} for row in rows]


def _keep_reviewed_rows(original: list[dict], current: list[dict], fields: dict) -> list[dict]:
    current_by_id = {row["public_id"]: row for row in current if row.get("public_id")}
    kept = []
    for row in original:
        matched = current_by_id.get(row.get("public_id"))
        kept.append(dict(matched) if matched and matched.get("disabled") else
            {**row, "public_id": row.get("public_id", "") if matched else ""})
    used = {row.get("public_id") for row in kept}
    # Current predecessors are still named, even when the explicit whole-section choice removes them.
    for row in current_by_id.values():
        if row["public_id"] not in used:
            kept.append(dict(row) if row.get("disabled") else
                {**dict.fromkeys(fields, ""), "public_id": row["public_id"], "errors": {}})
    return kept


def _review_rows(original, old, current, fields, choice):
    unchanged = old is not None and _row_values(original, fields) == _row_values(old, fields)
    peer_unchanged = old is not None and _row_values(old, fields) == _row_values(current, fields)
    if unchanged or choice == "current":
        return current, False
    if peer_unchanged or choice == "keep":
        return _keep_reviewed_rows(original, current, fields), False
    return original, True


def _review_without_basis(original: dict, current: dict, choice: str) -> tuple[dict, bool]:
    # A legacy form without its read basis cannot infer which fields the user changed.
    if choice == "keep":
        return {**current, **original}, False
    if choice == "current":
        return current, False
    return original, True


def _review_scalars(original: dict, basis: dict | None, current: dict, choice: str) -> tuple[dict, bool]:
    if basis is None:
        return _review_without_basis(original, current, choice)
    old = basis["values"]
    result = {**current, **{key: value for key, value in original.items() if key not in current}}
    groups = [("amount_yuan", "original_currency"), ("expense_time", *TIME_FIELDS)]
    grouped = {name for group in groups for name in group}
    groups.extend((name,) for name in current if name not in grouped)
    for group in groups:
        if any(name in original and original[name] != old.get(name) for name in group):
            result.update({name: original[name] for name in group if name in original})
    return result, False


def correction_review_response(db, request, options, selected_id, expense_id, form: CorrectionFormData, submitted: dict):
    ctx = web_correction_context(db, request, options, selected_id, expense_id, return_context=form.return_context)
    current = ctx["fact_current_basis"]
    basis = original_correction_basis(form.fact_basis, expense_id=expense_id)
    original = correction_form_projection(form)
    values, scalars_required = _review_scalars({key: value for key, value in original.form_values.items() if key in submitted},
        basis, current["values"], submitted.get("review_scalars_choice", ""))
    items, items_required = _review_rows(original.item_form_rows, basis["items"] if basis else None, current["items"], ITEM_FIELDS,
        submitted.get("review_items_choice", "") if "item_public_id" in submitted else "current")
    splits, splits_required = _review_rows(original.split_form_rows, basis["splits"] if basis else None, current["splits"], SPLIT_FIELDS,
        submitted.get("review_splits_choice", "") if "split_public_id" in submitted else "current")
    ready = not (scalars_required or items_required or splits_required)
    if ready:
        for name in ctx["frozen_scalars"]:
            values[name] = current["values"][name]
        values.update(expected_row_version=current["row_version"], fact_basis=json.dumps(current, ensure_ascii=False),
            draft_scope=form.draft_scope, idempotency_key=str(uuid4()),
            draft_client_ref=form.draft_client_ref or form.idempotency_key, reason=form.reason)
    else:
        values = original.form_values
        items, splits = original.item_form_rows, original.split_form_rows
    reviewed = web_correction_context(db, request, options, selected_id, expense_id, form_values=values,
        receipt_item_rows=items, split_form_rows=splits, return_context=form.return_context)
    reviewed.update(fact_review=current, fact_review_required={"scalars": scalars_required, "items": items_required, "splits": splits_required},
        fact_draft_result="prepared" if ready else "review", fact_review_ready=ready)
    return templates.TemplateResponse(request=request, name="expense_correct.html", context=reviewed)

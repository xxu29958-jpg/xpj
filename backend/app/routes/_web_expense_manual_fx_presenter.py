"""Manual-FX fields projected onto pending expense edit views."""

from __future__ import annotations


def _project_manual_fx(
    expense_view: dict,
    form_values: dict[str, str] | None,
) -> None:
    pending_foreign = (
        expense_view["status"] == "pending"
        and expense_view["is_foreign_currency"]
    )
    source_is_manual = expense_view["exchange_rate_source"] == "manual"
    if pending_foreign:
        expense_view["needs_amount"] = expense_view["original_amount_minor"] is None
    has_submitted_rate = bool(
        form_values and form_values.get("manual_exchange_rate", "").strip()
    )
    expense_view["manual_fx_editable"] = pending_foreign and (
        expense_view["fx_pending"] or source_is_manual or has_submitted_rate
    )
    if form_values is not None and "manual_exchange_rate" in form_values:
        expense_view["manual_exchange_rate_value"] = form_values[
            "manual_exchange_rate"
        ]
    elif source_is_manual and expense_view["exchange_rate_to_cny"] is not None:
        expense_view["manual_exchange_rate_value"] = str(
            expense_view["exchange_rate_to_cny"]
        )
    else:
        expense_view["manual_exchange_rate_value"] = ""
    expense_view["manual_fx_saved"] = (
        form_values is None
        and pending_foreign
        and source_is_manual
        and expense_view["fx_status"] == "ready"
    )


def project_manual_fx_edit_views(
    expense_view: dict,
    current_expense_view: dict,
    form_values: dict[str, str] | None,
) -> None:
    """Project persisted and submitted rate states for one edit response."""

    _project_manual_fx(current_expense_view, None)
    _project_manual_fx(expense_view, form_values)

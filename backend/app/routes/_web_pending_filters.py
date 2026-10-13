"""One presentation filter for the inbox and its full-page review position."""

from app.services.data_quality_service import is_ready_to_confirm_row, is_uncategorized_expense_category

PENDING_FILTERS = {"all", "missing_amount", "missing_merchant", "missing_category", "missing_fx", "duplicate", "ready"}


def matches_pending_filter(view: dict, filter_key: str) -> bool:
    if filter_key == "missing_amount":
        return view["needs_amount"]
    if filter_key == "missing_merchant":
        return view["needs_merchant"]
    if filter_key == "missing_category":
        # "其他" is an intentional category, not an uncategorized bill.
        return is_uncategorized_expense_category(view.get("category"))
    if filter_key == "missing_fx":
        return view["fx_pending"] and view["is_foreign_currency"] and view["original_amount_minor"] is not None
    if filter_key == "duplicate":
        return view["is_duplicate"]
    if filter_key == "ready":
        return is_ready_to_confirm_row(
            amount_cents=view["amount_cents"], merchant=view["merchant"], category=view.get("category"),
            duplicate_status=view["duplicate_status"], fx_status=view["fx_status"],
        )
    return True


def review_queue_position(views: list[dict], *, expense_id: int, filter_key: str) -> dict[str, int] | None:
    ids = [view["id"] for view in views if matches_pending_filter(view, filter_key.strip().lower())]
    if expense_id not in ids:
        return None
    return {"position": ids.index(expense_id) + 1, "total": len(ids)}

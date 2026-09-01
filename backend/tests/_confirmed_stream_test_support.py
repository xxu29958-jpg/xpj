from __future__ import annotations

from typing import Any


def confirmed_expense_roots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Project expense roots from the root-always confirmed stream envelope."""

    return [
        item["root"]
        for item in payload["items"]
        if item["entry_kind"] == "expense"
    ]

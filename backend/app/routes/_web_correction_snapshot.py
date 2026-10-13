"""Original browser form basis, separate from current facts and command fingerprints."""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.routes._web_accounting_time import TIME_FIELDS

ITEM_FIELDS = {"public_id": "item_public_id", "name": "item_name", "kind": "item_kind",
    "quantity_text": "item_quantity", "unit_price_yuan": "item_unit_price_yuan",
    "amount_yuan": "item_amount_yuan", "category": "item_category"}
SPLIT_FIELDS = {"public_id": "split_public_id", "member_id": "split_member_id",
    "amount_yuan": "split_amount_yuan", "note": "split_note"}
SCALAR_FIELDS = {"original_amount_value": "amount_yuan", "original_currency_code": "original_currency",
    "merchant": "merchant", "category_input": "category", "tags": "tags", "note": "note",
    "expense_time_local": "expense_time", "value_score": "value_score", "regret_score": "regret_score"}
SCALAR_GROUPS = {
    "amount_yuan": ("原币金额", ("original_currency", "amount_yuan")),
    "expense_time": ("账务时间", ("expense_time", *TIME_FIELDS)),
    "merchant": ("商家", ("merchant",)), "category": ("分类", ("category",)),
    "tags": ("标签", ("tags",)), "note": ("备注", ("note",)),
    "value_score": ("满意度", ("value_score",)), "regret_score": ("后悔度", ("regret_score",)),
}


@dataclass(frozen=True)
class CorrectionScalarComparison:
    key: str
    label: str
    fields: tuple[str, ...]
    current_values: dict[str, str]
    input_values: dict[str, str]
    changed: bool
    conflict: bool

    @property
    def current_text(self) -> str:
        return _comparison_text(self.key, self.current_values)

    @property
    def input_text(self) -> str:
        return _comparison_text(self.key, self.input_values)


def _comparison_text(key: str, values: dict[str, str]) -> str:
    if key == "expense_time":
        if values.get("time_precision") == "date_only":
            return values.get("user_local_date") or "未填写"
        return " · ".join(value for value in (values.get("expense_time", "").replace("T", " "),
            values.get("source_timezone", "")) if value) or "未填写"
    return " · ".join(value for value in values.values() if value) or "未填写"


def scalar_comparisons(original: dict[str, str], basis: dict | None,
                       current: dict[str, str]) -> list[CorrectionScalarComparison]:
    old = basis["values"] if basis else current
    rows = []
    for key, (label, fields) in SCALAR_GROUPS.items():
        mine = {name: original.get(name, old.get(name, "")) for name in fields}
        now = {name: current.get(name, "") for name in fields}
        changed = any(name in original and original[name] != old.get(name, "") for name in fields)
        peer_changed = any(now[name] != old.get(name, "") for name in fields)
        rows.append(CorrectionScalarComparison(key, label, fields, now, mine,
            changed, basis is not None and changed and peer_changed and mine != now))
    return rows


def raw_string(value) -> str:
    return "" if value is None else str(value)


def correction_snapshot(ctx: dict) -> dict:
    current = ctx["current_expense"]
    values = {name: raw_string(current.get(key)) for key, name in SCALAR_FIELDS.items()}
    time = ctx.get("current_time_form") or {}
    values.update({name: raw_string(time[name]) for name in TIME_FIELDS if name in time})
    return {"version": 1, "expense_id": str(current["id"]), "row_version": str(current["row_version"]),
        "values": values, "items": ctx["receipt_items"]["rows"], "splits": ctx["split_rows"]["rows"]}


def original_correction_basis(raw: str, *, expense_id: int) -> dict | None:
    try:
        basis = json.loads(raw)
        if not isinstance(basis, dict) or basis.get("version") != 1 or basis.get("expense_id") != str(expense_id):
            return None
        if not isinstance(basis.get("values"), dict) or not all(isinstance(basis.get(name), list) for name in ("items", "splits")):
            return None
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in basis["values"].items()):
            return None
        if not all(isinstance(row, dict) for name in ("items", "splits") for row in basis[name]):
            return None
        return basis
    except (ValueError, TypeError):
        return None

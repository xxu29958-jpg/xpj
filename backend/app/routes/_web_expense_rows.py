"""No-JavaScript expense item/split row parsing and error projection."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from app.errors import AppError
from app.routes._web_expense_form import parse_amount_yuan
from app.schemas import (
    ExpenseItemReplaceRequest,
    ExpenseItemRequest,
    ExpenseSplitReplaceRequest,
    ExpenseSplitRequest,
)


@dataclass(frozen=True)
class WebExpenseRowsOutcome:
    rows: list[dict]
    error: str | None = None
    error_status: int = 422


def item_replace_payload(
    *,
    currency_code: str,
    expected_row_version: int,
    item_name: list[str],
    item_kind: list[str],
    item_quantity: list[str],
    item_unit_price_yuan: list[str],
    item_amount_yuan: list[str],
    item_category: list[str],
) -> ExpenseItemReplaceRequest:
    items: list[ExpenseItemRequest] = []
    max_len = max(
        len(item_name),
        len(item_kind),
        len(item_quantity),
        len(item_unit_price_yuan),
        len(item_amount_yuan),
        len(item_category),
        0,
    )
    for index in range(max_len):
        name = _at(item_name, index).strip()
        kind_raw = _at(item_kind, index).strip() or "product"
        quantity = _at(item_quantity, index).strip()
        unit_raw = _at(item_unit_price_yuan, index)
        amount_raw = _at(item_amount_yuan, index)
        category = _at(item_category, index).strip()
        if not any((name, quantity, unit_raw.strip(), amount_raw.strip(), category)):
            continue
        if not name:
            _raise_form_row_error(index, "name", "明细名称不能为空。")
        unit_price_cents, unit_error = parse_amount_yuan(
            unit_raw,
            currency_code=currency_code,
        )
        amount_cents, amount_error = parse_amount_yuan(
            amount_raw,
            currency_code=currency_code,
        )
        if unit_error:
            _raise_form_row_error(index, "unit_price_yuan", unit_error)
        if amount_error:
            _raise_form_row_error(index, "amount_yuan", amount_error)
        if kind_raw == "discount" and amount_cents is not None:
            amount_cents = -abs(amount_cents)
        try:
            items.append(
                ExpenseItemRequest(
                    name=name,
                    kind=kind_raw,
                    quantity_text=quantity or None,
                    unit_price_cents=unit_price_cents,
                    amount_cents=amount_cents,
                    category=category or None,
                )
            )
        except ValueError as exc:
            field = _pydantic_form_field(exc, item=True)
            _raise_form_row_error(index, field, str(exc), cause=exc)
    try:
        return ExpenseItemReplaceRequest(
            expected_row_version=expected_row_version,
            items=items,
        )
    except ValidationError as exc:
        raise AppError(
            "invalid_request",
            "明细最多保存 200 行。",
            status_code=422,
        ) from exc


def split_replace_payload(
    *,
    currency_code: str,
    expected_row_version: int,
    split_member_id: list[str],
    split_amount_yuan: list[str],
    split_note: list[str],
) -> ExpenseSplitReplaceRequest:
    splits: list[ExpenseSplitRequest] = []
    max_len = max(len(split_member_id), len(split_amount_yuan), len(split_note), 0)
    for index in range(max_len):
        member_raw = _at(split_member_id, index).strip()
        amount_raw = _at(split_amount_yuan, index)
        note = _at(split_note, index).strip()
        if not any((member_raw, amount_raw.strip(), note)):
            continue
        if not member_raw or not amount_raw.strip():
            field = "member_id" if not member_raw else "amount_yuan"
            _raise_form_row_error(index, field, "拆账成员和金额都需要填写。")
        try:
            member_id = int(member_raw)
        except ValueError as exc:
            _raise_form_row_error(
                index,
                "member_id",
                "请选择正确的家庭成员。",
                cause=exc,
            )
        amount_cents, amount_error = parse_amount_yuan(
            amount_raw,
            currency_code=currency_code,
        )
        if amount_error or amount_cents is None:
            _raise_form_row_error(
                index,
                "amount_yuan",
                amount_error or "请填写正确的拆账金额。",
            )
        try:
            splits.append(
                ExpenseSplitRequest(
                    member_id=member_id,
                    amount_cents=amount_cents,
                    note=note or None,
                )
            )
        except ValidationError as exc:
            _raise_form_row_error(
                index,
                _pydantic_form_field(exc, item=False),
                str(exc),
                cause=exc,
            )
    try:
        return ExpenseSplitReplaceRequest(
            expected_row_version=expected_row_version,
            splits=splits,
        )
    except ValidationError as exc:
        raise AppError(
            "invalid_request",
            "家庭拆账最多保存 100 行。",
            status_code=422,
        ) from exc


def submitted_item_form_rows(
    *,
    item_name: list[str],
    item_kind: list[str],
    item_quantity: list[str],
    item_unit_price_yuan: list[str],
    item_amount_yuan: list[str],
    item_category: list[str],
) -> list[dict]:
    size = max(
        len(item_name),
        len(item_kind),
        len(item_quantity),
        len(item_unit_price_yuan),
        len(item_amount_yuan),
        len(item_category),
        0,
    )
    return [
        {
            "kind": _at(item_kind, index) or "product",
            "name": _at(item_name, index),
            "quantity_text": _at(item_quantity, index),
            "unit_price_yuan": _at(item_unit_price_yuan, index),
            "amount_yuan": _at(item_amount_yuan, index),
            "category": _at(item_category, index),
            "is_ocr_draft": False,
            "errors": {},
        }
        for index in range(size)
    ]


def submitted_split_form_rows(
    *,
    split_member_id: list[str],
    split_amount_yuan: list[str],
    split_note: list[str],
) -> list[dict]:
    size = max(len(split_member_id), len(split_amount_yuan), len(split_note), 0)
    rows: list[dict] = []
    for index in range(size):
        member_raw = _at(split_member_id, index)
        try:
            member_value: int | str = int(member_raw) if member_raw else ""
        except ValueError:
            member_value = member_raw
        rows.append(
            {
                "member_id": member_value,
                "account_name": "",
                "role": "",
                "amount_yuan": _at(split_amount_yuan, index),
                "note": _at(split_note, index),
                "disabled": False,
                "errors": {},
            }
        )
    return rows


def attach_form_row_error(rows: list[dict], exc: AppError) -> None:
    details = exc.details or {}
    row_index = details.get("row_index")
    field = details.get("field")
    if not isinstance(row_index, int) or not isinstance(field, str):
        return
    if 0 <= row_index < len(rows):
        rows[row_index].setdefault("errors", {})[field] = exc.message


def _at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _raise_form_row_error(
    row_index: int,
    field: str,
    message: str,
    *,
    cause: Exception | None = None,
) -> None:
    error = AppError(
        "invalid_request",
        message,
        status_code=422,
        details={"row_index": row_index, "field": field},
    )
    if cause is not None:
        raise error from cause
    raise error


def _pydantic_form_field(exc: ValueError, *, item: bool) -> str:
    if not isinstance(exc, ValidationError):
        return "row"
    field = str(exc.errors(include_url=False)[0].get("loc", ("row",))[-1])
    if item:
        return {
            "unit_price_cents": "unit_price_yuan",
            "amount_cents": "amount_yuan",
            "quantity_text": "quantity",
        }.get(field, field)
    return {"amount_cents": "amount_yuan", "member_id": "member_id"}.get(
        field,
        field,
    )

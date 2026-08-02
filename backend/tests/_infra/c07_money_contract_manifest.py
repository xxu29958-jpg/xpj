"""Shared fixtures and assertion helpers for the C07 money contract tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import BaseModel, ValidationError

from app.money_contract import (
    MONEY_COLUMNS_V1,
    MONEY_MINOR_MAX,
)
from app.schemas._bill_split import BillSplitInviteRequest
from app.schemas._debts import (
    DebtAdjustmentCreateRequest,
    DebtCreateRequest,
    MemberRepaymentProposalCreateRequest,
    RepaymentCreateRequest,
)
from app.schemas._exchange import ExchangeRateRequest
from app.schemas._expense import (
    ExpenseItemRequest,
    ExpenseManualCreateRequest,
    ExpenseUpdateRequest,
    NotificationDraftCreateRequest,
)
from app.schemas._money import (
    CANONICAL_NONNEGATIVE_MONEY_MINOR_TEXT_PATTERN,
)

EXPECTED_TABLES = {
    "bill_split_invitations",
    "budget_categories",
    "budgets",
    "category_rules",
    "csv_import_rows",
    "debt_adjustments",
    "debt_forgivenesses",
    "debts",
    "expense_items",
    "expense_splits",
    "expenses",
    "goals",
    "member_repayment_proposals",
    "monthly_income_plans",
    "ocr_facts",
    "recurring_items",
    "repayment_drafts",
    "repayments",
}
V1_FREEZE_SHA256 = (
    "5568462d6b011c3395f06004184b219eb5de93d7b986b28a0d294d8f5c3e7753"
)
POSITIVE_DECIMAL_REQUEST_FIELDS = (
    (
        ExchangeRateRequest,
        "rate_to_cny",
        {"currency_code": "USD", "rate_date": "2026-05-04"},
    ),
    (
        DebtCreateRequest,
        "original_amount",
        {"direction": "i_owe", "counterparty_type": "external"},
    ),
    (
        RepaymentCreateRequest,
        "original_amount",
        {"expected_row_version": 1},
    ),
    (
        MemberRepaymentProposalCreateRequest,
        "original_amount",
        {},
    ),
)
NONNEGATIVE_DECIMAL_REQUEST_FIELDS = (
    (ExpenseManualCreateRequest, "original_amount", {}),
    (
        NotificationDraftCreateRequest,
        "original_amount",
        {"source": "other"},
    ),
    (
        ExpenseUpdateRequest,
        "original_amount",
        {"expected_row_version": 1},
    ),
)


def v1_digest() -> str:
    digest = hashlib.sha256()
    for column in MONEY_COLUMNS_V1:
        for check in column.checks:
            digest.update(
                (
                    f"{column.table}|{column.column}|{column.nullable}|"
                    f"{check.name}|{check.predicate}\n"
                ).encode()
            )
    return digest.hexdigest()


def load_expand_migration() -> ModuleType:
    backend_root = Path(__file__).resolve().parents[2]
    path = (
        backend_root
        / "migrations"
        / "versions"
        / "20260729_0001_money_minor_bigint_expand.py"
    )
    spec = importlib.util.spec_from_file_location("money_bigint_expand", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def model_validate_json_field(
    model: type[BaseModel],
    field: str,
    base_payload: dict[str, object],
    value: object,
) -> Decimal:
    payload = {**base_payload, field: value}
    parsed = model.model_validate_json(json.dumps(payload))
    result = getattr(parsed, field)
    assert type(result) is Decimal
    return result


def schema_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(schema_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(schema_keys(item))
        return keys
    return set()


def string_schema(value: dict[str, object]) -> dict[str, object]:
    if value.get("type") == "string":
        return value
    any_of = value.get("anyOf")
    assert isinstance(any_of, list)
    matches = [
        item
        for item in any_of
        if isinstance(item, dict) and item.get("type") == "string"
    ]
    assert len(matches) == 1
    return matches[0]


def money_integer_schema_gaps(openapi: dict[str, object]) -> list[str]:
    gaps: list[str] = []

    def walk(node: object, path: str) -> None:
        if not isinstance(node, dict):
            return
        for name, child in node.get("properties", {}).items():
            if "_cents" in name or "_minor" in name:
                variants = [child, *child.get("anyOf", [])]
                for variant in variants:
                    if variant.get("type") != "integer":
                        continue
                    missing = {
                        key
                        for key in ("format", "minimum", "maximum")
                        if key not in variant
                    }
                    if variant.get("format") != "int64":
                        missing.add("format=int64")
                    if missing:
                        gaps.append(f"{path}.{name}: {sorted(missing)}")
            walk(child, f"{path}.{name}")
        for keyword in ("anyOf", "oneOf", "allOf"):
            for index, child in enumerate(node.get(keyword, [])):
                walk(child, f"{path}.{keyword}[{index}]")
        walk(node.get("items"), f"{path}.items")

    components = openapi["components"]["schemas"]
    for name, schema in components.items():
        walk(schema, name)
    return gaps


def _assert_bill_split_schema_contract() -> None:
    amount_schema = BillSplitInviteRequest.model_json_schema()["properties"][
        "amount_cents"
    ]
    assert amount_schema["minimum"] == 1
    assert amount_schema["maximum"] == MONEY_MINOR_MAX
    assert amount_schema["format"] == "int64"
    request = BillSplitInviteRequest(
        receiver_account_id=1,
        amount_cents=MONEY_MINOR_MAX,
    )
    assert request.amount_cents == MONEY_MINOR_MAX
    for value in (0, -1, MONEY_MINOR_MAX + 1, True, 1.0, "1"):
        with pytest.raises(ValidationError):
            BillSplitInviteRequest(
                receiver_account_id=1,
                amount_cents=value,
            )


def _assert_debt_adjustment_schema_contract() -> None:
    adjustment_schema = DebtAdjustmentCreateRequest.model_json_schema()[
        "properties"
    ]["amount_cents"]
    assert adjustment_schema["minimum"] == -MONEY_MINOR_MAX
    assert adjustment_schema["maximum"] == MONEY_MINOR_MAX
    assert adjustment_schema["format"] == "int64"
    assert adjustment_schema["not"] == {"const": 0}
    for value in (-1, 1):
        DebtAdjustmentCreateRequest(
            amount_cents=value,
            reason="correction",
            expected_row_version=1,
        )
    with pytest.raises(ValidationError):
        DebtAdjustmentCreateRequest(
            amount_cents=0,
            reason="correction",
            expected_row_version=1,
        )


def _assert_expense_item_schema_contract() -> None:
    item_schema = ExpenseItemRequest.model_json_schema()
    conditional = item_schema["allOf"][0]
    assert conditional["if"]["properties"]["kind"] == {"const": "discount"}
    discount_amount = conditional["then"]["properties"]["amount_cents"]["anyOf"][0]
    regular_amount = conditional["else"]["properties"]["amount_cents"]["anyOf"][0]
    assert (discount_amount["minimum"], discount_amount["maximum"]) == (
        -MONEY_MINOR_MAX,
        0,
    )
    assert (regular_amount["minimum"], regular_amount["maximum"]) == (
        0,
        MONEY_MINOR_MAX,
    )
    assert discount_amount["format"] == regular_amount["format"] == "int64"
    ExpenseItemRequest(name="discount", kind="discount", amount_cents=-1)
    ExpenseItemRequest(name="product", amount_cents=1)
    with pytest.raises(ValidationError):
        ExpenseItemRequest(name="discount", kind="discount", amount_cents=1)
    with pytest.raises(ValidationError):
        ExpenseItemRequest(name="product", amount_cents=-1)


def _assert_openapi_money_schema_contract() -> None:
    from app.main import app

    openapi = app.openapi()
    assert money_integer_schema_gaps(openapi) == []
    parameters = openapi["paths"]["/api/budget/discretionary"]["get"][
        "parameters"
    ]
    textual_money = {
        parameter["name"]: parameter["schema"]
        for parameter in parameters
        if parameter["name"]
        in {"savings_target_cents", "reserved_buffer_cents"}
    }
    assert set(textual_money) == {
        "savings_target_cents",
        "reserved_buffer_cents",
    }
    for schema in textual_money.values():
        # Query strings preserve lexical evidence so +1/01/space cannot be
        # normalized away before the canonical-money validator.
        assert schema["type"] == "string"
        assert schema["pattern"] == (
            CANONICAL_NONNEGATIVE_MONEY_MINOR_TEXT_PATTERN
        )
        assert schema["maxLength"] == len(str(MONEY_MINOR_MAX))


def assert_documented_money_schema_contract() -> None:
    """Assert the four schema surfaces pinned by the original test node."""

    _assert_bill_split_schema_contract()
    _assert_debt_adjustment_schema_contract()
    _assert_expense_item_schema_contract()
    _assert_openapi_money_schema_contract()

"""Machine pins for the ADR-0073 C07 money contract."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import BigInteger, CheckConstraint

import app.models  # noqa: F401
from app import money_contract_manifest, money_contract_types
from app.database_model_registry import Base
from app.errors import AppError, _validation_error_code
from app.money_contract import (
    MONEY_AGGREGATE_MAX,
    MONEY_COLUMNS_V1,
    MONEY_FINAL_CHECKS_V1,
    MONEY_MINOR_MAX,
    MoneySign,
    ensure_money_minor,
    fold_sum_to_int,
    is_canonical_money_minor_text,
    parse_canonical_money_minor,
    projection_sum_to_int,
    projection_values_average_to_int,
    round_minor_ratio_half_up,
)
from app.schemas._bill_split import BillSplitInviteRequest
from app.schemas._money import (
    CANONICAL_NONNEGATIVE_DECIMAL_INPUT_PATTERN,
    CANONICAL_POSITIVE_DECIMAL_INPUT_PATTERN,
    NonNegativeMoneyMinor,
    NonZeroSignedMoneyMinor,
    PositiveMoneyMinor,
    SignedMoneyMinor,
)
from app.schemas._recurring import RecurringItemCreateRequest
from tests._infra.c07_money_contract_manifest import (
    EXPECTED_TABLES as _EXPECTED_TABLES,
)
from tests._infra.c07_money_contract_manifest import (
    NONNEGATIVE_DECIMAL_REQUEST_FIELDS as _NONNEGATIVE_DECIMAL_REQUEST_FIELDS,
)
from tests._infra.c07_money_contract_manifest import (
    POSITIVE_DECIMAL_REQUEST_FIELDS as _POSITIVE_DECIMAL_REQUEST_FIELDS,
)
from tests._infra.c07_money_contract_manifest import (
    V1_FREEZE_SHA256 as _V1_FREEZE_SHA256,
)
from tests._infra.c07_money_contract_manifest import (
    assert_documented_money_schema_contract,
)
from tests._infra.c07_money_contract_manifest import (
    load_expand_migration as _load_expand_migration,
)
from tests._infra.c07_money_contract_manifest import (
    model_validate_json_field as _model_validate_json_field,
)
from tests._infra.c07_money_contract_manifest import (
    schema_keys as _schema_keys,
)
from tests._infra.c07_money_contract_manifest import (
    string_schema as _string_schema,
)
from tests._infra.c07_money_contract_manifest import (
    v1_digest as _v1_digest,
)


def test_public_money_contract_reexports_focused_contract_modules() -> None:
    assert money_contract_manifest.MONEY_COLUMNS_V1 is MONEY_COLUMNS_V1
    assert money_contract_types.MoneySign is MoneySign


def test_canonical_money_minor_text_is_linear_and_keeps_syntax_separate_from_bounds() -> None:
    for value in ("0", "1", "10", str(MONEY_MINOR_MAX), str(-MONEY_MINOR_MAX)):
        assert is_canonical_money_minor_text(value)

    for value in (None, 0, "", "-", "+1", "-0", "00", "01", "-01", " 1", "1 ", "1.0", "1e3", "９"):
        assert not is_canonical_money_minor_text(value)

    assert not is_canonical_money_minor_text("9" * 1_000_000)
    assert (
        parse_canonical_money_minor(
            str(-MONEY_MINOR_MAX),
            sign=MoneySign.SIGNED,
            label="amount",
        )
        == -MONEY_MINOR_MAX
    )
    assert is_canonical_money_minor_text(str(MONEY_MINOR_MAX + 1))
    with pytest.raises(AppError):
        parse_canonical_money_minor(
            str(MONEY_MINOR_MAX + 1),
            sign=MoneySign.SIGNED,
            label="amount",
        )


def test_v1_manifest_is_frozen() -> None:
    assert _v1_digest() == _V1_FREEZE_SHA256


def test_manifest_shape_is_exact() -> None:
    assert len(MONEY_COLUMNS_V1) == 30
    assert {column.table for column in MONEY_COLUMNS_V1} == _EXPECTED_TABLES
    assert len(_EXPECTED_TABLES) == 18
    assert tuple(sorted(MONEY_COLUMNS_V1, key=lambda column: (column.table, column.column))) == MONEY_COLUMNS_V1
    names = [check.name for check in MONEY_FINAL_CHECKS_V1]
    assert len(names) == len(set(names)) == 31
    assert all(len(name.encode()) <= 63 for name in names)


def test_c07_entry_and_permanent_bounds_are_identical() -> None:
    assert MONEY_MINOR_MAX == 9_000_000_000_000
    assert MONEY_AGGREGATE_MAX == 2**53 - 1
    for column in MONEY_COLUMNS_V1:
        if column.table == "debt_forgivenesses":
            assert str(MONEY_AGGREGATE_MAX) in column.final_check_predicate
            continue
        assert str(MONEY_MINOR_MAX) in column.final_check_predicate


def test_manifest_sign_semantics() -> None:
    by_key = {(column.table, column.column): column for column in MONEY_COLUMNS_V1}
    assert by_key[("budgets", "rollover_amount_cents")].sign is MoneySign.SIGNED
    adjustment = by_key[("debt_adjustments", "amount_cents")]
    assert adjustment.sign is MoneySign.SIGNED and adjustment.nonzero
    assert "<> 0" in adjustment.final_check_predicate
    assert by_key[("expense_items", "amount_cents")].sign is MoneySign.SIGNED
    item_amount = by_key[("expense_items", "amount_cents")]
    assert "kind = 'discount'" in item_amount.final_check_predicate
    assert "kind IN ('product', 'tax', 'service_fee')" in (item_amount.final_check_predicate)
    assert by_key[("expense_items", "unit_price_cents")].sign is MoneySign.NONNEGATIVE
    assert by_key[("expense_splits", "amount_cents")].sign is MoneySign.NONNEGATIVE
    goal = by_key[("goals", "target_amount_cents")]
    assert "goal_type = 'spending_limit'" in goal.final_check_predicate
    assert "target_amount_cents IS NOT NULL" in goal.final_check_predicate
    assert "goal_type = 'debt_repayment' AND target_amount_cents IS NULL" in goal.final_check_predicate
    goal_month = goal.checks[1]
    assert goal_month.name == "ck_goals_month_format"
    assert "month IS NOT NULL" in goal_month.predicate
    assert "goal_type = 'debt_repayment' AND month IS NULL" in (goal_month.predicate)


def test_orm_shape_matches_frozen_c07_manifest() -> None:
    contract_keys = {(column.table, column.column) for column in MONEY_COLUMNS_V1}
    metadata_keys = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith(("_cents", "_minor"))
    }
    assert metadata_keys == contract_keys

    for column_contract in MONEY_COLUMNS_V1:
        table = Base.metadata.tables[column_contract.table]
        column = table.columns[column_contract.column]
        assert isinstance(column.type, BigInteger)
        assert column.nullable is column_contract.nullable
        checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        for check in column_contract.checks:
            assert checks[check.name] == check.predicate
        assert not any(name and name.endswith("_c07_i4_hold") for name in checks)

    migration = _load_expand_migration()
    legacy_names = {name for names in migration._LEGACY_CHECKS.values() for name in names}
    orm_check_names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert legacy_names.isdisjoint(orm_check_names)


def test_migration_manifest_matches_runtime_contract() -> None:
    module = _load_expand_migration()
    assert module.revision == "20260729_0001"
    assert module.down_revision == "20260722_0001"
    generated_rows = []
    for column in MONEY_COLUMNS_V1:
        additional = column.checks[1:]
        assert len(additional) <= 1
        generated_rows.append(
            (
                column.table,
                column.column,
                column.nullable,
                column.final_check_name,
                column.final_check_predicate,
                additional[0].name if additional else None,
                additional[0].predicate if additional else None,
            )
        )
    generated = tuple(generated_rows)
    assert tuple(module._MANIFEST_ROWS) == generated
    assert tuple(module._MANIFEST) == tuple((*row, None) for row in generated)


def test_pydantic_types_are_strict_and_use_c07_release_bounds() -> None:
    class Probe(BaseModel):
        pos: PositiveMoneyMinor
        nonnegative: NonNegativeMoneyMinor
        nonzero_signed: NonZeroSignedMoneyMinor
        signed: SignedMoneyMinor

    Probe(pos=1, nonnegative=0, nonzero_signed=-1, signed=-MONEY_MINOR_MAX)
    Probe(
        pos=MONEY_MINOR_MAX,
        nonnegative=MONEY_MINOR_MAX,
        nonzero_signed=MONEY_MINOR_MAX,
        signed=MONEY_MINOR_MAX,
    )
    Probe(
        pos=2_147_483_648,
        nonnegative=2_147_483_648,
        nonzero_signed=2_147_483_648,
        signed=2_147_483_648,
    )
    for payload in (
        {"pos": "1", "nonnegative": 0, "nonzero_signed": 1, "signed": 0},
        {"pos": 1.0, "nonnegative": 0, "nonzero_signed": 1, "signed": 0},
        {"pos": True, "nonnegative": 0, "nonzero_signed": 1, "signed": 0},
        {"pos": 0, "nonnegative": 0, "nonzero_signed": 1, "signed": 0},
        {"pos": 1, "nonnegative": -1, "nonzero_signed": 1, "signed": 0},
        {"pos": 1, "nonnegative": 0, "nonzero_signed": 0, "signed": 0},
        {"pos": 1, "nonnegative": 0, "nonzero_signed": 1, "signed": MONEY_MINOR_MAX + 1},
        {"pos": 1, "nonnegative": 0, "nonzero_signed": 1, "signed": -MONEY_MINOR_MAX - 1},
    ):
        with pytest.raises(ValidationError):
            Probe(**payload)


def test_positive_canonical_decimal_models_validate_json_wire_values() -> None:
    accepted = {
        "0.01": Decimal("0.01"),
        "1": Decimal("1"),
        "1.0": Decimal("1.0"),
    }
    for model, field, base_payload in _POSITIVE_DECIMAL_REQUEST_FIELDS:
        for raw, expected in accepted.items():
            assert (
                _model_validate_json_field(
                    model,
                    field,
                    base_payload,
                    raw,
                )
                == expected
            )
        for raw in ("0", "0.0"):
            with pytest.raises(ValidationError):
                _model_validate_json_field(model, field, base_payload, raw)


def test_nonnegative_canonical_decimal_models_allow_json_zero() -> None:
    accepted = {
        "0": Decimal("0"),
        "0.0": Decimal("0.0"),
        "0.01": Decimal("0.01"),
        "1": Decimal("1"),
        "1.0": Decimal("1.0"),
    }
    for model, field, base_payload in _NONNEGATIVE_DECIMAL_REQUEST_FIELDS:
        for raw, expected in accepted.items():
            assert (
                _model_validate_json_field(
                    model,
                    field,
                    base_payload,
                    raw,
                )
                == expected
            )


@pytest.mark.parametrize(
    "invalid",
    (
        1,
        1.0,
        True,
        -1,
        "-1",
        "01",
        "01.0",
        "1e2",
        "1E+2",
        "+1",
        ".1",
        "1.",
        " 1",
        "1 ",
    ),
)
def test_canonical_decimal_models_reject_noncanonical_json(
    invalid: object,
) -> None:
    fields = (
        *_POSITIVE_DECIMAL_REQUEST_FIELDS,
        *_NONNEGATIVE_DECIMAL_REQUEST_FIELDS,
    )
    for model, field, base_payload in fields:
        with pytest.raises(ValidationError):
            _model_validate_json_field(model, field, base_payload, invalid)


def test_canonical_decimal_models_preserve_internal_decimal_contract() -> None:
    for model, field, base_payload in _POSITIVE_DECIMAL_REQUEST_FIELDS:
        parsed = model.model_validate({**base_payload, field: Decimal("0.01")})
        assert getattr(parsed, field) == Decimal("0.01")
        for invalid in (Decimal("0"), Decimal("-1")):
            with pytest.raises(ValidationError):
                model.model_validate({**base_payload, field: invalid})

    for model, field, base_payload in _NONNEGATIVE_DECIMAL_REQUEST_FIELDS:
        parsed = model.model_validate({**base_payload, field: Decimal("0")})
        assert getattr(parsed, field) == Decimal("0")
        with pytest.raises(ValidationError):
            model.model_validate({**base_payload, field: Decimal("-1")})


def test_canonical_decimal_json_schemas_use_only_string_constraints() -> None:
    forbidden = {"gt", "ge", "minimum", "exclusiveMinimum"}
    groups = (
        (
            _POSITIVE_DECIMAL_REQUEST_FIELDS,
            CANONICAL_POSITIVE_DECIMAL_INPUT_PATTERN,
            ("0.01", "1", "1.0"),
            ("0", "0.0", "-1", "01", "1e2"),
        ),
        (
            _NONNEGATIVE_DECIMAL_REQUEST_FIELDS,
            CANONICAL_NONNEGATIVE_DECIMAL_INPUT_PATTERN,
            ("0", "0.0", "0.01", "1", "1.0"),
            ("-1", "01", "1e2"),
        ),
    )
    for fields, pattern, accepted, rejected in groups:
        for model, field, _base_payload in fields:
            field_schema = model.model_json_schema()["properties"][field]
            assert forbidden.isdisjoint(_schema_keys(field_schema))
            string_schema = _string_schema(field_schema)
            assert string_schema["pattern"] == pattern
            assert string_schema["maxLength"] == 64
            for value in accepted:
                assert re.search(pattern, value) is not None
            for value in rejected:
                assert re.search(pattern, value) is None


def test_money_schemas_enforce_documented_c07_bounds_and_signs() -> None:
    assert_documented_money_schema_contract()


def test_validation_error_code_allows_only_explicit_domain_errors() -> None:
    with pytest.raises(ValidationError) as exc_info:
        BillSplitInviteRequest(receiver_account_id=1, amount_cents=0)
    assert _validation_error_code(RequestValidationError(exc_info.value.errors())) == "split_amount_invalid"

    with pytest.raises(ValidationError) as recurring_exc_info:
        RecurringItemCreateRequest(merchant="x" * 256, baseline_amount_cents=1)
    assert (
        _validation_error_code(RequestValidationError(recurring_exc_info.value.errors()))
        == "recurring_merchant_too_long"
    )

    unknown = RequestValidationError(
        [
            {
                "type": "unknown_custom_validation_error",
                "loc": ("body", "amount_cents"),
                "msg": "must not escape",
                "input": 0,
            }
        ]
    )
    assert _validation_error_code(unknown) == "invalid_request"

    mixed = RequestValidationError(
        [
            *exc_info.value.errors(),
            {
                "type": "unknown_custom_validation_error",
                "loc": ("body", "receiver_account_id"),
                "msg": "must not escape",
                "input": None,
            },
        ]
    )
    assert _validation_error_code(mixed) == "invalid_request"


def test_command_validator_rejects_non_int_and_preserves_domain_code() -> None:
    assert ensure_money_minor(1, sign=MoneySign.POSITIVE, label="t") == 1
    assert ensure_money_minor(0, sign=MoneySign.NONNEGATIVE, label="t") == 0
    assert ensure_money_minor(-1, sign=MoneySign.SIGNED, label="t") == -1
    assert (
        ensure_money_minor(
            MONEY_MINOR_MAX,
            sign=MoneySign.POSITIVE,
            label="t",
        )
        == MONEY_MINOR_MAX
    )
    assert (
        ensure_money_minor(
            -MONEY_MINOR_MAX,
            sign=MoneySign.SIGNED,
            label="t",
        )
        == -MONEY_MINOR_MAX
    )
    for value in (MONEY_MINOR_MAX + 1, -MONEY_MINOR_MAX - 1):
        with pytest.raises(AppError) as exc_info:
            ensure_money_minor(value, sign=MoneySign.SIGNED, label="t")
        assert exc_info.value.status_code == 422
    for value in (
        True,
        1.0,
        Decimal("1"),
        Decimal("NaN"),
        "1",
        None,
    ):
        with pytest.raises(AppError) as exc_info:
            ensure_money_minor(value, sign=MoneySign.SIGNED, label="t")
        assert exc_info.value.status_code == 422
    with pytest.raises(AppError) as exc_info:
        ensure_money_minor(
            0,
            sign=MoneySign.POSITIVE,
            label="split",
            error_code="split_amount_invalid",
        )
    assert exc_info.value.error == "split_amount_invalid"


def test_projection_sum_requires_explicit_empty_semantics() -> None:
    assert projection_sum_to_int(None, label="t", empty_is_zero=True) == 0
    assert projection_sum_to_int(Decimal("2147483648"), label="t") == 2_147_483_648
    with pytest.raises(AppError) as exc_info:
        projection_sum_to_int(None, label="t")
    assert exc_info.value.status_code == 500
    with pytest.raises(AppError):
        projection_sum_to_int(MONEY_AGGREGATE_MAX + 1, label="t")
    with pytest.raises(AppError):
        projection_sum_to_int(Decimal("1.9"), label="t")


def test_fold_sum_requires_explicit_empty_semantics() -> None:
    assert fold_sum_to_int(None, label="t", empty_is_zero=True) == 0
    assert fold_sum_to_int(Decimal(str(MONEY_AGGREGATE_MAX)), label="t") == MONEY_AGGREGATE_MAX
    with pytest.raises(AppError) as exc_info:
        fold_sum_to_int(None, label="t")
    assert exc_info.value.status_code == 409
    with pytest.raises(AppError):
        fold_sum_to_int(MONEY_AGGREGATE_MAX + 1, label="t")
    with pytest.raises(AppError):
        fold_sum_to_int(True, label="t")


def test_minor_ratio_rounding_is_exact_half_up_for_both_signs() -> None:
    assert round_minor_ratio_half_up(1, 2, label="t") == 1
    assert round_minor_ratio_half_up(-1, 2, label="t") == -1
    assert round_minor_ratio_half_up(2, 3, label="t") == 1
    assert round_minor_ratio_half_up(-2, 3, label="t") == -1
    with pytest.raises(AppError) as exc_info:
        round_minor_ratio_half_up(1, 0, label="t")
    assert exc_info.value.error == "money_projection_out_of_range"


def test_projection_average_bounds_values_and_not_exact_numerator() -> None:
    assert projection_values_average_to_int([], label="t") == 0
    assert projection_values_average_to_int([1, 2], label="t") == 2
    assert projection_values_average_to_int([-1, -2], label="t") == -2
    assert (
        projection_values_average_to_int(
            [MONEY_AGGREGATE_MAX, MONEY_AGGREGATE_MAX],
            label="t",
        )
        == MONEY_AGGREGATE_MAX
    )
    with pytest.raises(AppError):
        projection_values_average_to_int([MONEY_AGGREGATE_MAX + 1], label="t")

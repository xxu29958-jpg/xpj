"""Stable recurring merchant validation errors at the public API boundary."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.errors import _validation_error_code
from app.schemas._recurring import (
    RecurringCandidateConfirmRequest,
    RecurringItemCreateRequest,
    RecurringItemUpdateRequest,
)

_SCHEMA_CASES = (
    (RecurringCandidateConfirmRequest, {"amount_cents": 1}),
    (RecurringItemCreateRequest, {"baseline_amount_cents": 1}),
    (RecurringItemUpdateRequest, {"expected_row_version": 1}),
)


@pytest.mark.parametrize(("request_type", "other_fields"), _SCHEMA_CASES)
def test_recurring_merchant_schema_does_not_publish_false_raw_length_cap(
    request_type,
    other_fields: dict[str, object],
) -> None:
    canonical = "😀" * 255

    request = request_type(merchant=f"  {canonical} \n", **other_fields)

    assert request.merchant == canonical
    merchant_schema = request_type.model_json_schema()["properties"]["merchant"]
    string_schema = next(
        (branch for branch in merchant_schema.get("anyOf", []) if branch.get("type") == "string"),
        merchant_schema,
    )
    # The runtime contract trims outer whitespace before enforcing the
    # canonical 255-code-point display limit. JSON Schema maxLength applies to
    # the raw request instance and cannot express that transformation, so
    # publishing maxLength=255 would make generated clients reject this valid
    # request before the backend Owner can decide it.
    assert "maxLength" not in string_schema
    assert "Leading and trailing whitespace" in merchant_schema["description"]


@pytest.mark.parametrize(("request_type", "other_fields"), _SCHEMA_CASES)
def test_recurring_merchant_schema_preserves_required_code_after_outer_trim(
    request_type,
    other_fields: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        request_type(merchant=" \t\n ", **other_fields)

    request_errors = exc_info.value.errors()
    assert [error["type"] for error in request_errors] == ["recurring_merchant_required"]
    assert _validation_error_code(RequestValidationError(request_errors)) == "recurring_merchant_required"


def test_manual_recurring_create_counts_canonical_display_after_outer_trim(
    client: TestClient,
    *,
    identity,
) -> None:
    canonical = "😀" * 255
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}

    created = client.post(
        "/api/recurring/items",
        headers=headers,
        json={
            "merchant": f" {canonical}\n",
            "baseline_amount_cents": 1,
            "next_expected_date": "2026-09-05",
        },
    )

    assert created.status_code == 201, created.json()
    assert created.json()["merchant"] == canonical


def test_manual_recurring_create_preserves_required_error_after_outer_trim(
    client: TestClient,
    *,
    identity,
) -> None:
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}

    rejected = client.post(
        "/api/recurring/items",
        headers=headers,
        json={
            "merchant": " \t\n ",
            "baseline_amount_cents": 1,
            "next_expected_date": "2026-09-05",
        },
    )

    assert rejected.status_code == 422, rejected.json()
    assert rejected.json()["error"] == "recurring_merchant_required"


def test_candidate_confirmation_rejects_display_merchant_overflow_with_domain_error(
    client: TestClient,
    *,
    identity,
) -> None:
    response = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "x" * 256,
            "amount_cents": 20000,
            "occurrence_count": 3,
            "last_seen_at": "2026-05-05T12:00:00Z",
            "confidence": "high",
            "frequency": "monthly",
        },
    )

    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "recurring_merchant_too_long"

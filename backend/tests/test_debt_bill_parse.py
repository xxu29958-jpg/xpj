"""ADR-0049 §D 债务账单 OCR 解析：服务 provider + ``POST /api/debts/parse-bill`` 路由。

瞬态解析（不落库、不建债、不存图）：上传欠款截图 → 建议还款条款 → 预填建债表单。
§8 红线：建议非事实，``source_text`` 是源文本片段，用户确认/改后才建债（走 POST /api/debts）。
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from app.services import debt_bill_parse_service
from app.services.debt_bill_parse_service import (
    EmptyDebtBillProvider,
    LocalLlmDebtBillProvider,
    MockDebtBillProvider,
    _debt_bill_prompt_text,
    _suggestion_from_llm_json,
    get_debt_bill_provider,
    parse_debt_bill,
)
from tests._infra.assets import PNG_BYTES


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


# ── service layer ────────────────────────────────────────────────────────────


def test_parse_debt_bill_empty_provider_returns_blank_suggestion() -> None:
    suggestion = parse_debt_bill(PNG_BYTES, "image/png", provider_name="empty")

    assert suggestion.merchant is None
    assert suggestion.principal_amount_cents is None
    assert suggestion.installment_count is None
    assert suggestion.per_period_amount_cents is None
    assert suggestion.repayment_day is None
    assert suggestion.source_text == ""
    assert suggestion.confidence is None


def test_parse_debt_bill_mock_provider_returns_installment_terms() -> None:
    suggestion = parse_debt_bill(PNG_BYTES, "image/png", provider_name="mock")

    assert suggestion.merchant == "花呗"
    assert suggestion.principal_amount_cents == 120000
    assert suggestion.installment_count == 12
    assert suggestion.installment_period_months == 1
    assert suggestion.per_period_amount_cents == 10000
    assert suggestion.repayment_day == 10
    assert suggestion.source_text


def test_suggestion_from_llm_json_coerces_and_bounds_fields() -> None:
    # Out-of-range / zero values from the model must coerce to None (never a poisoned
    # prefill); confidence clamps into [0, 1]; valid fields pass through.
    suggestion = _suggestion_from_llm_json(
        {
            "merchant": "招商银行信用卡",
            "principal_amount_cents": 0,  # not > 0 → None
            "installment_count": 9999,  # > 600 → None
            "installment_period_months": 1,
            "per_period_amount_cents": -100,  # not > 0 → None
            "repayment_day": 40,  # > 28 → None
            "source_text": "账单分期 共12期",
            "confidence": 5,  # clamps to 1.0
        }
    )

    assert suggestion.merchant == "招商银行信用卡"
    assert suggestion.principal_amount_cents is None
    assert suggestion.installment_count is None
    assert suggestion.installment_period_months == 1
    assert suggestion.per_period_amount_cents is None
    assert suggestion.repayment_day is None
    assert suggestion.source_text == "账单分期 共12期"
    assert suggestion.confidence == 1.0


def test_debt_bill_prompt_requests_source_text_and_terms() -> None:
    prompt = _debt_bill_prompt_text()

    assert "JSON ONLY" in prompt
    assert "source_text" in prompt
    assert "installment_count" in prompt
    assert "repayment_day" in prompt
    # §8: must ask the model to copy source text rather than invent numbers.
    assert "do NOT invent" in prompt


def test_get_debt_bill_provider_dispatch() -> None:
    assert isinstance(get_debt_bill_provider("mock"), MockDebtBillProvider)
    assert isinstance(get_debt_bill_provider("local_llm"), LocalLlmDebtBillProvider)
    assert isinstance(get_debt_bill_provider("empty"), EmptyDebtBillProvider)
    # Unknown / unconfigured → empty (fall back to manual entry, never raise).
    assert isinstance(get_debt_bill_provider("nope"), EmptyDebtBillProvider)


# ── route: POST /api/debts/parse-bill ────────────────────────────────────────


def test_parse_bill_route_returns_mock_suggestion(client: TestClient, monkeypatch, *, identity) -> None:
    monkeypatch.setattr(
        debt_bill_parse_service,
        "get_settings",
        lambda: SimpleNamespace(debt_bill_provider="mock"),
    )

    response = client.post(
        "/api/debts/parse-bill",
        headers=identity.app_headers,
        files={"file": ("bill.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["merchant"] == "花呗"
    assert body["installment_count"] == 12
    assert body["installment_period_months"] == 1
    assert body["per_period_amount_cents"] == 10000
    assert body["repayment_day"] == 10
    assert body["source_text"]


def test_parse_bill_route_unauthenticated_is_401(client: TestClient) -> None:
    # coverage: auth-401
    response = client.post(
        "/api/debts/parse-bill",
        files={"file": ("bill.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 401


def test_parse_bill_route_rejects_non_image(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/debts/parse-bill",
        headers=identity.app_headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_file_type"


def test_parse_bill_route_viewer_is_403(client: TestClient, *, identity) -> None:
    # coverage: viewer-write
    _set_owner_ledger_role("viewer")

    response = client.post(
        "/api/debts/parse-bill",
        headers=identity.app_headers,
        files={"file": ("bill.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 403

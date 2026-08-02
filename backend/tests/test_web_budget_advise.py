"""Parity checks for /web/budget-advise live-provider gates."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import reset_settings_cache
from app.database import SessionLocal
from app.models import BudgetAdvisorAuditLog, LedgerMember
from app.services.budget_advisor_service import _providers as providers_module


@pytest.fixture()
def live_provider_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "deepseek")
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "test-model")
    monkeypatch.setenv("BUDGET_ADVISOR_API_KEY", "test-key")
    monkeypatch.setenv("BUDGET_ADVISOR_LIVE_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("BUDGET_ADVISOR_LIVE_DAILY_CALL_LIMIT", "0")
    reset_settings_cache()
    yield monkeypatch
    reset_settings_cache()


@pytest.fixture()
def jpy_home_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _patch_openai_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, body):
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":"web ok","suggestions":[],"confidence":0.5}'
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(
        providers_module.OpenAiCompatBudgetAdvisor,
        "_post_chat_completion",
        fake_post,
    )


def _set_owner_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def _audit_rows() -> list[BudgetAdvisorAuditLog]:
    with SessionLocal() as db:
        return (
            db.query(BudgetAdvisorAuditLog)
            .order_by(BudgetAdvisorAuditLog.id.asc())
            .all()
        )


def _audit_count() -> int:
    return len(_audit_rows())


def test_web_get_run_advise_does_not_call_live_provider(
    web_client: TestClient, *, identity, live_provider_env
) -> None:
    before_count = _audit_count()

    response = web_client.get(
        "/web/budget-advise?ledger_id=owner&month=2026-05&run_advise=true"
    )

    assert response.status_code == 200, response.text
    assert _audit_count() == before_count


def test_web_budget_advise_form_keeps_csrf_token_out_of_get_url(
    web_client: TestClient, *, identity
) -> None:
    response = web_client.get("/web/budget-advise?ledger_id=owner&month=2026-05")

    assert response.status_code == 200, response.text
    assert 'method="post"' in response.text
    assert 'name="csrf_token"' in response.text
    assert 'method="get"' not in response.text
    assert "formmethod" not in response.text


def test_web_budget_advise_post_defaults_money_to_canonical_zero_text(
    web_client: TestClient, *, identity
) -> None:
    response = web_client.post(
        "/web/budget-advise",
        data={"ledger_id": "owner", "month": "2026-05"},
    )

    assert response.status_code == 200, response.text
    assert 'name="savings_target_yuan"' in response.text
    assert (
        'name="savings_target_yuan" min="0" step="0.01" inputmode="decimal" '
        'placeholder="0.00" value="0"'
    ) in response.text
    assert (
        'name="reserved_buffer_yuan" min="0" step="0.01" inputmode="decimal" '
        'placeholder="0.00" value="0"'
    ) in response.text


def test_web_budget_advise_post_accepts_canonical_cny_decimal_text(
    web_client: TestClient, *, identity
) -> None:
    response = web_client.post(
        "/web/budget-advise",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "savings_target_yuan": "12.34",
            "reserved_buffer_yuan": "0.1",
        },
    )

    assert response.status_code == 200, response.text
    assert "− ¥12.34 储蓄目标" in response.text
    assert "− ¥0.10 备用金" in response.text
    assert (
        'name="savings_target_yuan" min="0" step="0.01" inputmode="decimal" '
        'placeholder="0.00" value="12.34"'
    ) in response.text
    assert (
        'name="reserved_buffer_yuan" min="0" step="0.01" inputmode="decimal" '
        'placeholder="0.00" value="0.1"'
    ) in response.text


def test_web_budget_advise_post_accepts_canonical_jpy_integer_text(
    jpy_home_env, web_client: TestClient, *, identity
) -> None:
    response = web_client.post(
        "/web/budget-advise",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "savings_target_yuan": "1234",
        },
    )

    assert response.status_code == 200, response.text
    assert "− ¥1234 储蓄目标" in response.text
    assert (
        'name="savings_target_yuan" min="0" step="1" inputmode="numeric" '
        'placeholder="0" value="1234"'
    ) in response.text


@pytest.mark.parametrize(
    "amount_text",
    ("12.5", "1e2", "abc", "9000000000001"),
    ids=("fraction", "exponent", "invalid", "c07-overflow"),
)
def test_web_budget_advise_post_rejects_noncanonical_or_out_of_range_jpy_text(
    jpy_home_env,
    web_client: TestClient,
    *,
    identity,
    amount_text: str,
) -> None:
    response = web_client.post(
        "/web/budget-advise",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "savings_target_yuan": amount_text,
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"] == "amount_invalid"


def test_web_live_provider_without_owner_confirm_does_not_audit(
    web_client: TestClient, *, identity, live_provider_env
) -> None:
    live_provider_env.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "false")
    reset_settings_cache()
    before_count = _audit_count()

    response = web_client.post(
        "/web/budget-advise",
        data={"ledger_id": "owner", "month": "2026-05", "run_advise": "true"},
    )

    assert response.status_code == 200, response.text
    assert _audit_count() == before_count


def test_web_live_provider_requires_owner_role(
    web_client: TestClient, *, identity, live_provider_env, monkeypatch
) -> None:
    live_provider_env.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "true")
    reset_settings_cache()
    _set_owner_role("member")
    _patch_openai_call(monkeypatch)
    before_count = _audit_count()

    response = web_client.post(
        "/web/budget-advise",
        data={"ledger_id": "owner", "month": "2026-05", "run_advise": "true"},
    )

    assert response.status_code == 200, response.text
    assert _audit_count() == before_count


def test_web_live_provider_records_audit_with_owner_confirm(
    web_client: TestClient, *, identity, live_provider_env, monkeypatch
) -> None:
    live_provider_env.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "true")
    reset_settings_cache()
    _patch_openai_call(monkeypatch)
    before_count = _audit_count()

    response = web_client.post(
        "/web/budget-advise",
        data={"ledger_id": "owner", "month": "2026-05", "run_advise": "true"},
    )

    assert response.status_code == 200, response.text
    assert "web ok" in response.text
    rows = _audit_rows()
    assert len(rows) == before_count + 1
    row = rows[-1]
    assert row.provider == "openai_compat"
    assert row.model == "test-model"
    assert row.month == "2026-05"
    assert row.success == 1

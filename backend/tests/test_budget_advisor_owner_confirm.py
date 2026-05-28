"""v1.1 Batch 2: AI budget advisor owner-confirm + audit + status.

Three new surfaces:

* ``/api/budget/advise`` refuses to call a live provider unless
  ``BUDGET_ADVISOR_OWNER_CONFIRMED=true``.
* Every live call writes a ``budget_advisor_audit_logs`` row.
* ``GET /api/budget/advisor/status`` returns the masked provider config
  + the most recent audit row's outcome.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import reset_settings_cache
from app.database import SessionLocal
from app.models import BudgetAdvisorAuditLog, LedgerMember
from app.services.budget_advisor_service import _providers as providers_module
from app.services.budget_advisor_service._audit import cleanup_expired_audit_logs
from app.services.time_service import now_utc


@pytest.fixture()
def live_provider_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BUDGET_ADVISOR_PROVIDER", "openai_compat")
    monkeypatch.setenv("BUDGET_ADVISOR_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("BUDGET_ADVISOR_MODEL", "test-model")
    monkeypatch.setenv("BUDGET_ADVISOR_API_KEY", "test-key")
    monkeypatch.setenv("BUDGET_ADVISOR_LIVE_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("BUDGET_ADVISOR_LIVE_DAILY_CALL_LIMIT", "0")
    reset_settings_cache()
    yield monkeypatch
    reset_settings_cache()


def _patch_openai_call(monkeypatch: pytest.MonkeyPatch, *, payload: dict) -> None:
    def fake_post(self, body):
        return payload

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


def test_cleanup_expired_audit_logs_does_not_block_on_older_unexpired_rows(
    *, identity
) -> None:
    now = now_utc()
    with SessionLocal() as db:
        db.add(
            BudgetAdvisorAuditLog(
                tenant_id="owner",
                actor_account_id=None,
                provider="openai_compat",
                model="test",
                input_hash="old-long-retention",
                success=1,
                retention_days=180,
                called_at=now - timedelta(days=100),
            )
        )
        db.add(
            BudgetAdvisorAuditLog(
                tenant_id="owner",
                actor_account_id=None,
                provider="openai_compat",
                model="test",
                input_hash="new-expired-short-retention",
                success=1,
                retention_days=30,
                called_at=now - timedelta(days=40),
            )
        )
        db.commit()

        assert cleanup_expired_audit_logs(db, now=now, batch_size=1) == 1
        remaining = {
            row.input_hash for row in db.query(BudgetAdvisorAuditLog).all()
        }

    assert remaining == {"old-long-retention"}


def test_live_provider_without_owner_confirm_returns_403(
    client: TestClient, *, identity, live_provider_env
) -> None:
    response = client.post(
        "/api/budget/advise",
        headers=identity.app_headers,
        json={"month": "2026-05", "timezone": "Asia/Shanghai"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "ai_advisor_not_confirmed"


def test_live_provider_requires_owner_role(
    client: TestClient, *, identity, live_provider_env, monkeypatch
) -> None:
    live_provider_env.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "true")
    reset_settings_cache()
    _set_owner_role("member")
    _patch_openai_call(
        monkeypatch,
        payload={
            "choices": [
                {"message": {"content": '{"summary":"ok","suggestions":[]}'}}
            ]
        },
    )

    response = client.post(
        "/api/budget/advise",
        headers=identity.app_headers,
        json={"month": "2026-05", "timezone": "Asia/Shanghai"},
    )

    assert response.status_code == 403
    assert response.json()["error"] == "ai_advisor_owner_required"
    with SessionLocal() as db:
        assert db.query(BudgetAdvisorAuditLog).count() == 0


def test_live_provider_with_owner_confirm_records_audit(
    client: TestClient, *, identity, live_provider_env, monkeypatch
) -> None:
    live_provider_env.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "true")
    reset_settings_cache()
    _patch_openai_call(
        monkeypatch,
        payload={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":"ok","suggestions":[],"confidence":0.5}'
                        )
                    }
                }
            ]
        },
    )

    response = client.post(
        "/api/budget/advise",
        headers=identity.app_headers,
        json={"month": "2026-05", "timezone": "Asia/Shanghai"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider_name"] == "openai_compat"

    with SessionLocal() as db:
        rows = (
            db.query(BudgetAdvisorAuditLog)
            .order_by(BudgetAdvisorAuditLog.id.desc())
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.provider == "openai_compat"
        assert row.model == "test-model"
        assert row.month == "2026-05"
        assert row.success == 1
        assert row.input_hash != "unknown"
        # Masked base url keeps the legitimate path; only credentials
        # embedded in the URL are stripped.
        assert row.base_url == "http://127.0.0.1:11434/v1"


def test_live_provider_min_interval_blocks_repeated_calls(
    client: TestClient, *, identity, live_provider_env, monkeypatch
) -> None:
    live_provider_env.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "true")
    live_provider_env.setenv("BUDGET_ADVISOR_LIVE_MIN_INTERVAL_SECONDS", "60")
    reset_settings_cache()
    _patch_openai_call(
        monkeypatch,
        payload={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":"ok","suggestions":[],"confidence":0.5}'
                        )
                    }
                }
            ]
        },
    )

    first = client.post(
        "/api/budget/advise",
        headers=identity.app_headers,
        json={"month": "2026-05", "timezone": "Asia/Shanghai"},
    )
    second = client.post(
        "/api/budget/advise",
        headers=identity.app_headers,
        json={"month": "2026-05", "timezone": "Asia/Shanghai"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 429
    assert second.json()["error"] == "ai_advisor_rate_limited"
    with SessionLocal() as db:
        assert db.query(BudgetAdvisorAuditLog).count() == 1


def test_advisor_status_reflects_provider_config(
    client: TestClient, *, identity, live_provider_env
) -> None:
    live_provider_env.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "false")
    reset_settings_cache()
    response = client.get(
        "/api/budget/advisor/status", headers=identity.app_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "openai_compat"
    assert body["model"] == "test-model"
    assert body["is_live"] is True
    assert body["owner_confirmed"] is False
    assert body["needs_confirmation"] is True
    assert body["last_called_at"] is None


def test_advisor_status_after_call_shows_last_outcome(
    client: TestClient, *, identity, live_provider_env, monkeypatch
) -> None:
    live_provider_env.setenv("BUDGET_ADVISOR_OWNER_CONFIRMED", "true")
    reset_settings_cache()
    _patch_openai_call(
        monkeypatch,
        payload={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":"ok","suggestions":'
                            '[{"category":"餐饮","suggested_amount_cents":12000,'
                            '"rationale":"r"}],"confidence":0.7}'
                        )
                    }
                }
            ]
        },
    )
    advise = client.post(
        "/api/budget/advise",
        headers=identity.app_headers,
        json={"month": "2026-05", "timezone": "Asia/Shanghai"},
    )
    assert advise.status_code == 200, advise.text

    response = client.get(
        "/api/budget/advisor/status", headers=identity.app_headers
    )
    body = response.json()
    assert body["last_success"] is True
    assert body["last_suggestion_count"] == 1
    assert body["last_called_at"] is not None
    assert "input_hash" not in body

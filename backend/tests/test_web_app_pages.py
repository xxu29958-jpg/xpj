"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense


def test_web_pending_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/pending")
    assert resp.status_code == 200
    assert "待确认" in resp.text


def test_web_confirmed_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/confirmed")
    assert resp.status_code == 200
    assert "已确认" in resp.text


def test_web_stats_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/stats?month=2026-05")
    assert resp.status_code == 200
    assert "月度统计" in resp.text


def test_web_stats_reports_recurring_candidate_errors(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routes import web_stats as web_stats_module

    def fail_recurring_candidates(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_stats_module, "recurring_candidates", fail_recurring_candidates)

    resp = web_client.get("/web/stats?month=2026-05")

    assert resp.status_code == 200
    assert "固定支出候选分析暂时不可用" in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/web/stats?month=2026-13",
        "/web/confirmed?month=0000-05",
        "/web/categories?month=2026-5",
    ],
)
def test_web_month_pages_reject_invalid_month_labels(
    web_client: TestClient, path: str
) -> None:
    resp = web_client.get(path)
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"


def test_web_search_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/search?ledger_id=owner")
    assert resp.status_code == 200
    assert 'name="q"' in resp.text

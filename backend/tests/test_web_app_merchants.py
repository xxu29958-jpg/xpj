"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense


def test_web_merchants_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/merchants?ledger_id=owner")
    assert resp.status_code == 200
    assert "商家治理" in resp.text
    assert "不会覆盖原始账单商家" in resp.text


def test_web_merchants_alias_create_toggle_delete(web_client: TestClient) -> None:
    created = web_client.post(
        "/web/merchants/aliases/create",
        data={
            "canonical_merchant": "星巴克",
            "alias": "STARBUCKS 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    page = web_client.get("/web/merchants?ledger_id=owner")
    assert page.status_code == 200
    assert "STARBUCKS 国贸店" in page.text
    assert "starbucks 国贸店" in page.text

    duplicate = web_client.post(
        "/web/merchants/aliases/create",
        data={
            "canonical_merchant": "另一家",
            "alias": "starbucks 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=True,
    )
    assert duplicate.status_code == 200
    assert "商家别名已指向其他商家" in duplicate.text

    import re as _re
    match = _re.search(r"/web/merchants/aliases/([^/]+)/delete", page.text)
    assert match, page.text[:500]
    public_id = match.group(1)

    toggled = web_client.post(
        f"/web/merchants/aliases/{public_id}/toggle",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert toggled.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "停用" in page.text

    deleted = web_client.post(
        f"/web/merchants/aliases/{public_id}/delete",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert deleted.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "还没有商家别名" in page.text

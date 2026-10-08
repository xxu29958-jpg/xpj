"""The native adapter shares ledger queries without gaining a second write authority."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember, SavedView
from tests._web_public_session_support import public_client

pytestmark = pytest.mark.real_db


def test_public_app_query_is_ledger_bound_and_current_viewer_cannot_replay_writes(identity):
    definition = {"name": "我的日用查询", "month_mode": "fixed", "month": "2026-10", "filter": "",
        "tag_public_id": None, "home_currency_code": "JPY", "query_text": "便利店", "category": "购物"}
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    with public_client() as api:
        assert api.get("/api/saved-views").status_code == 401
        response = api.post("/api/saved-views", headers=headers, json=definition)
        assert response.status_code == 201, response.text
        saved = response.json()
        path = f"/api/saved-views/{saved['public_id']}"
        assert api.get(path, headers=identity.app_headers).json() == saved
        assert api.get(path, headers=identity.gray_app_headers).status_code == 404
        assert api.get("/api/saved-views", headers=identity.gray_app_headers).json() == {"items": []}
        with SessionLocal.begin() as db:
            member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner"))
            member.role = "viewer"
        assert api.get(path, headers=identity.app_headers).json() == saved
        assert api.post("/api/saved-views", headers=headers, json=definition).status_code == 403
        assert api.patch(path, headers=headers, json={**definition, "expected_row_version": 1}).status_code == 403
        assert api.request("DELETE", path, headers=headers, json={"expected_row_version": 1}).status_code == 403
    with SessionLocal() as db:
        current = db.scalar(select(SavedView).where(SavedView.public_id == saved["public_id"]))
        assert (current.name, current.row_version, current.query_text) == (definition["name"], 1, "便利店")

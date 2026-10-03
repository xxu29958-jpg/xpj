"""The existing upload capability must land in the ledger selected in Owner UI."""

import re
from html import unescape
from urllib.parse import urlsplit

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import Account, Device, Expense, Ledger, LedgerMember, UploadLink
from app.routes.owner_console import _require_local
from app.services import owner_console_service
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES


@pytest.fixture
def owner(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://family.example.com")
    get_settings.cache_clear()
    app.dependency_overrides[_require_local] = lambda: None
    try:
        yield client
    finally:
        app.dependency_overrides.pop(_require_local, None)
        get_settings.cache_clear()


def _other_ledger(client, identity):
    created = client.post("/api/ledgers", headers=identity.admin_headers, json={"name": "旅行"})
    assert created.status_code == 201, created.text
    return created.json()["ledger_id"]


def _capability_counts(db):
    return tuple(db.scalar(select(func.count()).select_from(model)) for model in (Device, UploadLink))


def test_selected_ledger_owns_the_link_and_actual_uploaded_receipt(owner, identity):
    target = _other_ledger(owner, identity)
    with SessionLocal() as db:
        existing = {row.public_id: row.ledger_id for row in db.scalars(select(UploadLink))}
        default = owner_console_service.get_default_ledger_id(db)
    page = owner.get("/owner/upload-links")
    assert 'name="ledger_id"' in page.text and f'value="{target}"' in page.text
    created = owner.post("/owner/upload-links", data={"ledger_id": target})
    assert created.status_code == 200, created.text
    assert f'value="{target}" selected' in created.text
    assert '这条链接上传到：<strong>旅行</strong>' in created.text
    url = unescape(re.search(r'data-upload-handoff-url>([^<]+)</div>', created.text).group(1))
    parsed = urlsplit(url)
    received = owner.post(parsed.path + "?" + parsed.query, content=PNG_BYTES, headers={"Content-Type": "image/png"})
    assert received.status_code == 200, received.text
    with SessionLocal() as db:
        fresh = [row for row in db.scalars(select(UploadLink)) if row.public_id not in existing]
        assert len(fresh) == 1 and fresh[0].ledger_id == target
        assert db.get(Expense, received.json()["id"]).tenant_id == target
        assert {row.public_id: row.ledger_id for row in db.scalars(select(UploadLink)) if row.public_id in existing} == existing
        assert owner_console_service.get_default_ledger_id(db) == default
    assert parsed.path not in owner.get("/owner/upload-links").text


@pytest.mark.parametrize("reason", ["foreign", "archived", "lost_owner"])
def test_unavailable_selected_ledger_cannot_mint_a_device_or_upload_link(owner, identity, reason):
    target = _other_ledger(owner, identity)
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == target))
        if reason == "foreign":
            outsider = Account(display_name="另一个家庭")
            db.add(outsider)
            db.flush()
            ledger.owner_account_id = outsider.id
        elif reason == "archived":
            ledger.archived_at = now_utc()
        else:
            db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == target,
                LedgerMember.account_id == ledger.owner_account_id)).role = "member"
        db.commit()
        before = _capability_counts(db)
    denied = owner.post("/owner/upload-links", data={"ledger_id": target})
    assert denied.status_code == 404, denied.text
    assert "data-upload-handoff-url" not in denied.text
    assert '<option value="" selected disabled>请选择可管理的账本</option>' in denied.text
    with SessionLocal() as db:
        assert _capability_counts(db) == before

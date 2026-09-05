"""A local browser write keeps the installation Account and Web Device actor."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuthToken, CategoryRule, Device, ExpenseRevision, LedgerMember, Tag
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret
from tests._local_web_identity_support import (
    _InstalledWeb,
    _local_confirmation,
    installed_web_setup,
)

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web() -> Iterator[_InstalledWeb]:
    yield from installed_web_setup()


def test_real_web_mutation_is_attributed_to_installation_account_and_browser_device(
    installed_web: _InstalledWeb,
) -> None:
    _, csrf_token, cookie_header = _local_confirmation(installed_web)
    connected = installed_web.browser.post(
        "/web/auth/local",
        data={
            "csrf_token": csrf_token,
            "ledger_id": installed_web.shared_ledger_id,
            "next": "/web/tags",
        },
        headers={"Cookie": cookie_header, "Origin": "http://127.0.0.1:8000"},
        follow_redirects=False,
    )
    session_token = connected.cookies.get(SESSION_COOKIE_NAME)
    assert session_token is not None
    seeded = installed_web.browser.post(
        "/api/expenses/manual",
        headers={"Authorization": f"Bearer {session_token}"},
        json={
            "amount_cents": 1200,
            "merchant": "本机身份归属",
            "category": "餐饮",
            "expense_time": "2026-09-05T00:00:00Z",
            "tags": "待核对",
        },
    )
    assert seeded.status_code == 200, seeded.text
    expense_id = seeded.json()["id"]
    with SessionLocal() as db:
        tag = db.scalar(
            select(Tag)
            .where(Tag.tenant_id == installed_web.shared_ledger_id)
            .where(Tag.name == "待核对")
        )
        assert tag is not None
        tag_public_id = tag.public_id

    page = installed_web.browser.get(
        f"/web/tags?ledger_id={installed_web.shared_ledger_id}",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
    )
    token_match = re.search(
        rf'/web/tags/{tag_public_id}/rename.*?expected_row_version"\s*value="([^"]+)"',
        page.text,
        flags=re.DOTALL,
    )
    assert token_match is not None, page.text
    renamed = installed_web.browser.post(
        f"/web/tags/{tag_public_id}/rename",
        data={
            "csrf_token": csrf_token,
            "ledger_id": installed_web.shared_ledger_id,
            "expected_row_version": token_match.group(1),
            "name": "已核对",
        },
        headers={
            "Cookie": f"{cookie_header}; {SESSION_COOKIE_NAME}={session_token}",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert renamed.status_code == 303, renamed.text

    with SessionLocal() as db:
        token = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(session_token))
        )
        assert token is not None
        device = db.get(Device, token.device_id)
        revision = db.scalar(
            select(ExpenseRevision)
            .where(ExpenseRevision.expense_id == expense_id)
            .order_by(ExpenseRevision.revision_number.desc())
            .limit(1)
        )
        assert device is not None
        assert revision is not None
        assert revision.actor_account_id == installed_web.installation_account_id
        assert revision.actor_device_public_id == device.public_id


def test_viewer_connects_and_reads_but_native_web_write_is_denied(
    installed_web: _InstalledWeb,
) -> None:
    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == installed_web.shared_ledger_id)
            .where(LedgerMember.account_id == installed_web.installation_account_id)
        )
        assert membership is not None
        membership.role = "viewer"
        db.commit()

    preview, csrf_token, cookie_header = _local_confirmation(installed_web)
    assert "只读" in preview.text
    connected = installed_web.browser.post(
        "/web/auth/local",
        data={
            "csrf_token": csrf_token,
            "ledger_id": installed_web.shared_ledger_id,
            "next": "/web/pending",
        },
        headers={"Cookie": cookie_header, "Origin": "http://127.0.0.1:8000"},
        follow_redirects=False,
    )
    session_token = connected.cookies.get(SESSION_COOKIE_NAME)
    assert session_token is not None
    page = installed_web.browser.get(
        f"/web/pending?ledger_id={installed_web.shared_ledger_id}",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
    )
    assert page.status_code == 200, page.text
    assert "只读角色" in page.text

    denied = installed_web.browser.post(
        "/web/rules/create",
        data={
            "csrf_token": csrf_token,
            "ledger_id": installed_web.shared_ledger_id,
            "keyword": "不应写入",
            "category": "餐饮",
        },
        headers={
            "Cookie": f"{cookie_header}; {SESSION_COOKIE_NAME}={session_token}",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"] == "permission_denied"
    with SessionLocal() as db:
        assert db.scalar(
            select(CategoryRule.id)
            .where(CategoryRule.tenant_id == installed_web.shared_ledger_id)
            .where(CategoryRule.keyword == "不应写入")
        ) is None

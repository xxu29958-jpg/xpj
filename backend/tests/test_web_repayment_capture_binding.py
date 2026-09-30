"""Installed browser review: bound original input, lost reply and one real PG fact."""

import html
import json
import re
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.errors import AppError
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import Debt, Repayment
from app.routes import _web_repayment_review as review
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.schemas import RepaymentDraftCreateRequest
from app.services.debt_service import create_repayment_draft
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests.test_web_correction_fx_continuation import _NativeForm
from tests.test_web_repayment_binding import _installed_scope, _seed_external_debt

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web():
    yield from installed_web_setup()


def _form(text, action):
    native = _NativeForm(text, action, identity_fields=("csrf_token", "idempotency_key"))
    return {name: native.one(name) for name in native.fields}


def test_installed_capture_review_retains_binding_money_and_version_through_lost_ack(installed_web, monkeypatch):
    debt_id = _seed_external_debt(installed_web)
    with SessionLocal() as db:
        draft = create_repayment_draft(db, tenant_id=installed_web.shared_ledger_id,
            actor_account_id=installed_web.installation_account_id,
            payload=RepaymentDraftCreateRequest(source="alipay", original_currency="CNY", original_amount="100.00"))
        db.commit()
        public_id = draft.public_id
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_id))
        version = debt.row_version
    url = f"/web/repayment-drafts/{public_id}?ledger_id={installed_web.shared_ledger_id}"
    action = f"/web/repayment-drafts/{public_id}/review"
    token = _connect_local_session(installed_web, next_url=url)
    cookie = f"{SESSION_COOKIE_NAME}={token}"
    page = installed_web.browser.get(url, headers={"Cookie": cookie})
    assert page.status_code == 200, page.text
    headers = {"Cookie": f"{cookie}; {CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}",
        "Origin": "http://127.0.0.1:8000"}
    original = {**_form(page.text, action), "original_amount": "90.00", "target_with_expected_row_version": f"{debt_id}:{version}"}
    scope = _installed_scope(installed_web, token)
    assert json.loads(original["origin_binding"]) == scope
    for axis in scope:
        attempted = {**original, "origin_binding": json.dumps({**scope, axis: str(uuid4())})}
        refused = installed_web.browser.post(action, data=attempted, headers=headers)
        assert refused.status_code == 409, (axis, refused.text)
        retained = _form(refused.text, action)
        assert all(retained[name] == value for name, value in attempted.items() if name != "csrf_token")
        assert "data-repayment-ack=" not in refused.text
        with SessionLocal() as db:
            assert list(db.scalars(select(Repayment))) == []
    writer = review.confirm_repayment_draft_idempotently

    def lose_ack(*args, **kwargs):
        writer(*args, **kwargs)
        raise AppError("dependency_unavailable", "回包中断", status_code=503)

    monkeypatch.setattr(review, "confirm_repayment_draft_idempotently", lose_ack)
    unknown = installed_web.browser.post(action, data=original, headers=headers)
    assert unknown.status_code == 503, unknown.text
    assert 'data-repayment-result="submitted"' in unknown.text
    retained = _form(unknown.text, action)
    assert all(retained[name] == value for name, value in original.items() if name != "csrf_token")
    monkeypatch.setattr(review, "confirm_repayment_draft_idempotently", writer)
    reader = review.list_repayment_draft_audit_for_account

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("isolated projection outage")

    monkeypatch.setattr(review, "list_repayment_draft_audit_for_account", unavailable)
    receipt_id = None
    for _ in range(2):
        accepted = installed_web.browser.post(action, data=original, headers=headers)
        assert accepted.status_code == 200, accepted.text
        marker = re.search(r'data-repayment-ack="([^"]+)"', accepted.text)
        assert marker is not None
        ack = json.loads(html.unescape(marker[1]))
        assert ack["clientRef"] == original["idempotency_key"] and ack["scope"] == scope
        assert ack["resultPublicId"] == public_id and ack["status"] == "confirmed"
        with SessionLocal() as db:
            facts = list(db.scalars(select(Repayment)))
            assert len(facts) == 1
            assert facts[0].amount_cents == 9000 and facts[0].idempotency_key == original["idempotency_key"]
            assert facts[0].actor_account_id == installed_web.installation_account_id
            assert ack["repaymentPublicId"] == facts[0].public_id
            assert receipt_id is None or receipt_id == facts[0].public_id
            receipt_id = facts[0].public_id
    monkeypatch.setattr(review, "list_repayment_draft_audit_for_account", reader)
    history = installed_web.browser.get(url, headers=headers)
    assert history.status_code == 200 and "¥100.00" in history.text and "已记账" in history.text
    assert f"/web/debts/{debt_id}?ledger_id={installed_web.shared_ledger_id}" in history.text
    reused = installed_web.browser.post(action, data={**original, "original_amount": "95.00"}, headers=headers)
    assert reused.status_code == 422 and "不能认定本次处理成功" in reused.text
    assert "data-repayment-ack=" not in reused.text
    assert _form(reused.text, action)["idempotency_key"] == original["idempotency_key"]

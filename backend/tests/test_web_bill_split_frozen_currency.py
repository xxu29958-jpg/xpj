"""Issue #264: the Web split-invite form parses with the parent's frozen currency.

An Owner default-currency change keeps recorded money in its own currency.
The invitation freezes the parent expense's ``home_currency_code``, so the
form's typed major amount must be parsed with that same currency — never
with today's installation default — and every later surface (row version,
sent list, remaining capacity, received expense) must agree with it.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.currency_binding_contract import CURRENCY_CONTRACT_VERSION
from app.database import SessionLocal
from app.main import app
from app.models import Account, Expense, InstallationCurrencyBinding, Ledger, LedgerMember
from app.routes.web_common import _require_local as _web_require_local
from app.services import bill_split_service as bsplit
from app.services import currency_default_service as defaults
from app.services.bill_split_service import _create as split_create
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import currency_input_metadata, minor_amount_label
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.ledger_calendar_service import adopt_ledger_calendar
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import now_utc


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    try:
        yield client
    finally:
        app.dependency_overrides.pop(_web_require_local, None)


@pytest.fixture()
def change_default(monkeypatch: pytest.MonkeyPatch):
    """Run the shipped Owner default-change command; desktop re-auth is not under test."""
    monkeypatch.setattr(defaults, "revalidate_currency_adoption_owner", lambda db, auth: auth)
    owner = SimpleNamespace(account_public_id=str(uuid4()), device_public_id=str(uuid4()))

    def change(code: str) -> None:
        with SessionLocal() as db:
            revision = db.get(InstallationCurrencyBinding, 1).binding_revision
            defaults.change_currency_binding_for_installation_owner(db, auth=owner, idempotency_key=uuid4(),
                expected_contract_version=CURRENCY_CONTRACT_VERSION, home_code=code,
                expected_revision=revision, reason="issue 264 regression")

    return change


def _owner_account_id() -> int:
    with SessionLocal() as db:
        return db.query(Account).order_by(Account.id.asc()).first().id


def _add_receiver() -> int:
    with SessionLocal() as db:
        account = Account(display_name="分摊接收人")
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=account.id, role="member"))
        db.commit()
        return account.id


def _record_parent(currency: str, amount_minor: int, *, ledger_id: str = "owner") -> int:
    with SessionLocal() as db:
        resolve_write_capability(db)
        expense = Expense(tenant_id=ledger_id, amount_cents=amount_minor, home_currency_code=currency,
            original_currency_code=currency, original_amount_minor=amount_minor, merchant="Ramen",
            category="餐饮", source="iPhone截图", status="confirmed", expense_time=now_utc(),
            confirmed_at=now_utc())
        refresh_legacy_expense_time(db, expense)
        db.add(expense)
        db.commit()
        return expense.id


def _parent_under_other_default(change_default, *, frozen: str, runtime: str, amount_minor: int) -> int:
    """Record the parent while ``frozen`` is the default, then switch the default to ``runtime``."""
    if frozen != "CNY":
        change_default(frozen)
    expense_id = _record_parent(frozen, amount_minor)
    change_default(runtime)
    with SessionLocal() as db:
        assert db.get(InstallationCurrencyBinding, 1).home_currency_code == runtime
    return expense_id


def _invite_form(web_client: TestClient, expense_id: int) -> str:
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert page.status_code == 200, page.text
    return page.text[page.text.index('class="split-invite-form"'):]


def _form_value(form: str, name: str) -> str:
    return re.search(rf'name="{name}" value="([^"]+)"', form).group(1)


def _sent_for(expense_id: int) -> list:
    with SessionLocal() as db:
        return bsplit.list_sent_for_expense(db, sender_account_id=_owner_account_id(), expense_id=expense_id)


@pytest.mark.real_db
def test_web_and_command_same_key_share_claim_before_parent_lock(web_client: TestClient, monkeypatch) -> None:
    receiver_id = _add_receiver()
    expense_id = _record_parent("CNY", 5000)
    sender_id = _owner_account_id()
    key = str(uuid4())
    claimed, web_claiming = Event(), Event()
    original_claim = split_create._claim_invitation

    def coordinated_claim(db, **kwargs):
        if db.info.get("peer"):
            result = original_claim(db, **kwargs)
            claimed.set()
            assert web_claiming.wait(10), "Web request never reached the original claim"
            return result
        web_claiming.set()
        return original_claim(db, **kwargs)

    def peer():
        try:
            with SessionLocal() as db:
                db.info["peer"] = True
                return bsplit.create_invitation(db, sender_account_id=sender_id, sender_ledger_id="owner",
                    expense_id=expense_id, receiver_account_id=receiver_id, amount_cents=1000,
                    idempotency_key=key, expected_row_version=1).public_id
        except Exception as exc:
            return exc

    monkeypatch.setattr(split_create, "_claim_invitation", coordinated_claim)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(peer)
        assert claimed.wait(10), "Command did not claim its original key"
        try:
            response = web_client.post(f"/web/expenses/{expense_id}/split-invite",
                data={"ledger_id": "owner", "receiver_account_id": str(receiver_id), "amount_yuan": "10.00",
                    "expected_row_version": "1", "idempotency_key": key}, follow_redirects=False)
        except Exception as exc:
            response = exc
        original = pending.result(timeout=15)
    assert not isinstance(original, Exception), repr(original)
    assert not isinstance(response, Exception), repr(response)
    assert response.status_code == 303, response.text
    [invitation] = _sent_for(expense_id)
    assert (invitation.public_id, invitation.amount_cents, invitation.home_currency_code) == (original, 1000, "CNY")


@pytest.mark.parametrize(
    ("frozen", "runtime", "parent_minor", "typed", "share_minor", "too_precise"),
    [
        pytest.param("JPY", "CNY", 5000, "10", 10, "10.5", id="jpy-parent-cny-default"),
        pytest.param("KRW", "CNY", 50000, "10", 10, "10.5", id="krw-parent-cny-default"),
        pytest.param("USD", "JPY", 5000, "12.34", 1234, "12.345", id="usd-parent-jpy-default"),
    ],
)
def test_split_invite_parses_and_presents_with_parent_frozen_currency(
    web_client: TestClient, change_default, frozen: str, runtime: str, parent_minor: int,
    typed: str, share_minor: int, too_precise: str,
) -> None:
    receiver_id = _add_receiver()
    expense_id = _parent_under_other_default(change_default, frozen=frozen, runtime=runtime,
        amount_minor=parent_minor)
    url = f"/web/expenses/{expense_id}/split-invite"

    form = _invite_form(web_client, expense_id)
    rendered_version = _form_value(form, "expected_row_version")
    assert re.search(r'id="split-invite-amount"[^>]*step="([^"]+)"', form).group(1) == (
        currency_input_metadata(frozen)["amount_step"])
    assert f"本张账单还可分摊 {minor_amount_label(parent_minor, frozen)}" in form
    fields = {"ledger_id": "owner", "receiver_account_id": str(receiver_id),
        "expected_row_version": rendered_version}

    # Precision the frozen currency cannot hold is refused, never rescaled.
    refused = web_client.post(url, data={**fields, "amount_yuan": too_precise,
        "idempotency_key": str(uuid4())}, follow_redirects=False)
    assert refused.status_code == 422, refused.text
    assert "拆账金额不正确" in refused.text
    assert _sent_for(expense_id) == []

    created = web_client.post(url, data={**fields, "amount_yuan": typed,
        "idempotency_key": _form_value(form, "idempotency_key")}, follow_redirects=False)
    assert created.status_code == 303, created.text
    [invitation] = _sent_for(expense_id)
    assert (invitation.amount_cents, invitation.home_currency_code) == (share_minor, frozen)
    with SessionLocal() as db:
        assert str(db.get(Expense, expense_id).row_version) == rendered_version

    sent = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert f"{frozen} {minor_amount_label(share_minor, frozen)}" in sent.text
    after = _invite_form(web_client, expense_id)
    assert f"本张账单还可分摊 {minor_amount_label(parent_minor - share_minor, frozen)}" in after
    assert minor_amount_label(share_minor, frozen) in after

    with SessionLocal() as db:
        resolve_write_capability(db)
        ledger = Ledger(ledger_id=f"split-fx-{frozen.lower()}", name="接收账本", owner_account_id=receiver_id)
        db.add(ledger)
        db.flush()
        adopt_ledger_calendar(db, ledger_id=ledger.ledger_id, timezone_name="Asia/Shanghai",
            actor_account_id=receiver_id)
        db.add(LedgerMember(ledger_id=ledger.ledger_id, account_id=receiver_id, role="owner"))
        db.commit()
        _accepted, received = bsplit.accept_invitation(db, public_id=invitation.public_id,
            accepting_account_id=receiver_id, target_ledger_id=ledger.ledger_id)
        assert (received.amount_cents, received.home_currency_code) == (share_minor, frozen)


def test_split_invite_fails_closed_when_parent_binding_or_version_drifts(
    web_client: TestClient, change_default,
) -> None:
    receiver_id = _add_receiver()
    expense_id = _parent_under_other_default(change_default, frozen="JPY", runtime="CNY", amount_minor=5000)
    form = _invite_form(web_client, expense_id)
    fields = {"ledger_id": "owner", "receiver_account_id": str(receiver_id), "amount_yuan": "10",
        "expected_row_version": _form_value(form, "expected_row_version")}

    # The JPY fact the form was rendered for is re-stamped before submission.
    with SessionLocal() as db:
        resolve_write_capability(db)
        parent = db.get(Expense, expense_id)
        parent.amount_cents = parent.original_amount_minor = 5000
        parent.home_currency_code = parent.original_currency_code = "CNY"
        bump_row_version(parent)
        db.commit()
    stale = web_client.post(f"/web/expenses/{expense_id}/split-invite",
        data={**fields, "idempotency_key": str(uuid4())}, follow_redirects=False)
    assert stale.status_code == 409, stale.text
    assert "重新核对账单后发起" in stale.text
    assert _sent_for(expense_id) == []

    # A parent outside the authorized ledger is never read for its currency.
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.add(Ledger(ledger_id="split-fx-foreign", name="别人的账本", owner_account_id=receiver_id))
        db.flush()
        adopt_ledger_calendar(db, ledger_id="split-fx-foreign", timezone_name="Asia/Shanghai",
            actor_account_id=receiver_id)
        db.add(LedgerMember(ledger_id="split-fx-foreign", account_id=receiver_id, role="owner"))
        db.commit()
    foreign_id = _record_parent("CNY", 5000, ledger_id="split-fx-foreign")
    foreign = web_client.post(f"/web/expenses/{foreign_id}/split-invite",
        data={**fields, "expected_row_version": "1", "idempotency_key": str(uuid4())}, follow_redirects=False)
    assert foreign.status_code == 303
    assert "flash_type=error" in foreign.headers["location"]
    assert _sent_for(foreign_id) == []

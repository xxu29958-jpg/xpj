"""ADR-0043 P1 regression: a /web session gates writes on the SESSION's role.

``list_console_ledgers`` reports the local account as ``owner`` on its ledgers,
but a paired *viewer* device's Web session must stay read-only
(ENGINEERING_RULES §14). ``_resolve_selected_ledger_id`` stamps the session role
onto the matching option so the shared write-gate
(``_require_selected_ledger_write``) sees ``viewer``, not the console's
``owner``. Without the fix a Web viewer could mutate any /web route.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.errors import AppError
from app.routes.web_common import (
    LedgerOption,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
)


def _option(ledger_id: str, role: str) -> LedgerOption:
    return LedgerOption(
        ledger_id=ledger_id,
        name="家庭账本",
        role=role,
        is_default=True,
        pending_count=0,
        confirmed_count=0,
    )


class _SessionRequest:
    """Minimal stand-in for a Request carrying a verified web session."""

    def __init__(self, ledger_id: str, role: str) -> None:
        auth = type("_Auth", (), {"ledger_id": ledger_id, "role": role})()
        self.state = type("_State", (), {"web_session_auth": auth})()


def test_web_session_viewer_cannot_write_even_when_console_lists_owner() -> None:
    options = [_option("L1", "owner")]  # owner-console perspective
    request = _SessionRequest("L1", "viewer")  # paired viewer device

    selected = _resolve_selected_ledger_id(None, None, options, request=request)

    assert selected == "L1"
    assert options[0].role == "viewer", "session role must override the console role"
    with pytest.raises(AppError) as exc:
        _require_selected_ledger_write(options, selected)
    assert exc.value.error == "permission_denied"
    assert exc.value.status_code == 403


def test_web_session_member_may_write() -> None:
    options = [_option("L1", "owner")]
    request = _SessionRequest("L1", "member")

    selected = _resolve_selected_ledger_id(None, None, options, request=request)

    assert options[0].role == "member"
    _require_selected_ledger_write(options, selected)  # no raise


def test_write_gate_denies_when_ledger_is_not_an_option() -> None:
    """Hardening: a WRITE gate never falls back to options[0]."""
    options = [_option("L1", "owner")]
    with pytest.raises(AppError) as exc:
        _require_selected_ledger_write(options, "L2-not-listed")
    assert exc.value.status_code == 403


class _DesktopSessionRequest:
    """Minimal stand-in for a Request carrying a verified desktop bridge session."""

    def __init__(self, auth, *, method: str = "POST") -> None:
        self.method = method
        self.state = type(
            "_State",
            (),
            {"web_session_auth": auth, "web_session_platform": "desktop"},
        )()


def _foreign_ledger_with_desktop_session(*, role: str):
    from app.database import SessionLocal
    from app.models import Account, Ledger

    with SessionLocal() as db:
        account = Account(display_name=f"desktop-foreign-{uuid4()}")
        db.add(account)
        db.flush()
        ledger = Ledger(ledger_id=f"ledger_foreign_{uuid4().hex[:8]}", name="外部家庭账本", owner_account_id=account.id)
        db.add(ledger)
        db.commit()
        token, account, device = _mint_desktop_session(ledger_id=ledger.ledger_id, role=role)
        return ledger, token, account, device


def test_desktop_session_write_gate_uses_scoped_session_ledger_off_roster(identity) -> None:
    from app.database import SessionLocal

    # The console roster lacks the bound ledger entirely; the write gate must
    # authorize from the authenticated session, not the console enumeration.
    ledger, token, account, device = _foreign_ledger_with_desktop_session(role="member")
    auth = _auth_context(
        token,
        account,
        device,
        ledger_id=ledger.ledger_id,
        role="member",
        ledger_name="外部家庭账本",
    )
    request = _DesktopSessionRequest(auth)
    options = [_option("L1", "owner")]

    with SessionLocal() as db:
        selected = _resolve_selected_ledger_id(db, None, options, request=request)

    assert selected == ledger.ledger_id
    assert [opt.ledger_id for opt in options] == [ledger.ledger_id]
    assert options[0].role == "member"
    assert options[0].name == "外部家庭账本"
    _require_selected_ledger_write(options, selected)  # no raise


def test_desktop_session_viewer_cannot_write_off_roster(identity) -> None:
    from app.database import SessionLocal

    ledger, token, account, device = _foreign_ledger_with_desktop_session(role="viewer")
    auth = _auth_context(token, account, device, ledger_id=ledger.ledger_id, role="viewer")
    request = _DesktopSessionRequest(auth)
    options = [_option("L1", "owner")]

    with SessionLocal() as db:
        selected = _resolve_selected_ledger_id(db, None, options, request=request)

    with pytest.raises(AppError) as exc:
        _require_selected_ledger_write(options, selected)
    assert exc.value.error == "permission_denied"
    assert exc.value.status_code == 403


def test_desktop_session_options_scoped_to_bound_ledger_on_roster(identity) -> None:
    from app.database import SessionLocal

    # The bound ledger IS in the console roster, but with the console's role:
    # the session's live role wins and every foreign row is dropped.
    token, account, device = _mint_desktop_session(ledger_id="owner", role="member")
    auth = _auth_context(token, account, device, ledger_id="owner", role="member")
    request = _DesktopSessionRequest(auth)
    options = [_option("tester_1", "owner"), _option("owner", "viewer")]

    with SessionLocal() as db:
        selected = _resolve_selected_ledger_id(db, None, options, request=request)

    assert selected == "owner"
    assert [opt.ledger_id for opt in options] == ["owner"]
    assert options[0].role == "member"
    _require_selected_ledger_write(options, selected)  # no raise


# ── Desktop bridge principal: lock-time revalidation in the handler transaction ──


def _mint_desktop_session(*, ledger_id: str = "owner", role: str = "member"):
    from app.database import SessionLocal
    from app.models import Account, AuthToken, Device, Ledger, LedgerMember
    from app.services.identity_service import hash_secret, new_session_token

    token_value = new_session_token()
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id))
        assert ledger is not None
        account = Account(display_name=f"desktop-reval-{role}-{uuid4()}")
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role=role))
        device = Device(account_id=account.id, device_name="pytest-reval-desktop", platform="desktop")
        db.add(device)
        db.flush()
        token = AuthToken(
            token_hash=hash_secret(token_value),
            account_id=account.id,
            device_id=device.id,
            ledger_id=ledger_id,
            scope="app",
        )
        db.add(token)
        db.commit()
        return token, account, device


def _auth_context(token, account, device, *, ledger_id: str, role: str, ledger_name: str = "我的小票夹"):
    from app.tenants import AuthContext

    return AuthContext(
        account_id=account.id,
        account_public_id=account.public_id,
        account_name=account.display_name,
        ledger_id=ledger_id,
        ledger_name=ledger_name,
        device_id=device.id,
        device_public_id=device.public_id,
        device_name=device.device_name,
        role=role,
        scope="app",
        credential_id=token.id,
        credential_hash=token.token_hash,
    )


def test_desktop_principal_revalidated_inside_the_handler_transaction(identity) -> None:
    from app.database import SessionLocal
    from app.models import LedgerMember

    token, account, device = _mint_desktop_session(role="owner")
    auth = _auth_context(token, account, device, ledger_id="owner", role="owner")
    request = _DesktopSessionRequest(auth)
    options = [_option("tester_1", "owner")]

    with SessionLocal() as db:
        selected = _resolve_selected_ledger_id(db, None, options, request=request)
    assert selected == "owner"
    assert [opt.ledger_id for opt in options] == ["owner"]
    assert options[0].role == "owner"

    # Demotion between the middleware check and the handler's transaction is
    # picked up by the lock-time revalidation: the live role wins immediately.
    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.account_id == account.id)
        )
        membership.role = "viewer"
        db.commit()
    with SessionLocal() as db:
        _resolve_selected_ledger_id(db, None, options, request=request)
    assert request.state.web_session_auth.role == "viewer"
    assert options[0].role == "viewer"
    with pytest.raises(AppError) as exc:
        _require_selected_ledger_write(options, "owner")
    assert exc.value.status_code == 403


def _kill_credential_cause(db, cause: str, *, token, account, device) -> None:
    from app.models import Account, AuthToken, Device, Ledger, LedgerMember
    from app.services.time_service import now_utc

    if cause == "membership":
        row = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.account_id == account.id)
        )
        row.disabled_at = now_utc()
        return
    if cause == "device":
        db.get(Device, device.id).revoked_at = now_utc()
        return
    if cause == "token":
        db.get(AuthToken, token.id).revoked_at = now_utc()
        return
    if cause == "account":
        db.get(Account, account.id).disabled_at = now_utc()
        return
    db.scalar(select(Ledger).where(Ledger.ledger_id == "owner")).archived_at = now_utc()


@pytest.mark.parametrize("revoke", ["membership", "device", "token", "account", "archived"])
def test_desktop_principal_dead_mid_transaction_is_401(identity, revoke: str) -> None:
    from app.database import SessionLocal
    from app.models import AuthToken

    token, account, device = _mint_desktop_session(role="member")
    auth = _auth_context(token, account, device, ledger_id="owner", role="member")
    request = _DesktopSessionRequest(auth)
    options = [_option("tester_1", "owner")]

    with SessionLocal() as db:
        _kill_credential_cause(db, revoke, token=token, account=account, device=device)
        db.commit()

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        _resolve_selected_ledger_id(db, None, options, request=request)
    assert exc.value.error == "invalid_token"
    assert exc.value.status_code == 401

    # Death is durable (the middleware's membership-loss invariant): when the
    # cause left the token row alive, the revalidation hard-revoked it, so a
    # membership re-enable or un-archive cannot resurrect the bearer.
    with SessionLocal() as db:
        stored = db.get(AuthToken, token.id)
    assert stored.revoked_at is not None
    assert stored.grace_until is None

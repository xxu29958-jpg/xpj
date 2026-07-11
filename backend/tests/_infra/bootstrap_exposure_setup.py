"""State builders for bootstrap exposure recovery tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.services.invitation_invites as invitation_invites
import app.services.invitation_members as invitation_members
from app.database import SessionLocal
from app.main import app
from app.models import (
    Account,
    AuthToken,
    Device,
    Ledger,
    LedgerMember,
    PairingCode,
    UploadLink,
)
from app.services.identity_service import hash_pairing_code, hash_secret
from app.services.time_service import now_utc
from tests._infra.bootstrap_recovery import (
    _VECTOR_PAIRING_CODE,
    _VECTOR_SECRET,
    _VECTOR_UPLOAD_KEY,
    _post_bootstrap,
)


@dataclass(frozen=True)
class _MemberEvidence:
    account_id: int
    device_id: int
    membership_id: int
    session_hash: str


@dataclass(frozen=True)
class _ExposureWindow:
    stale_pairing_session: Session
    stale_pairing_id: int
    stale_pairing_hash: str
    exposed_session_hash: str
    exposed_invite_token: str
    bootstrap_account_id: int
    bootstrap_membership_id: int
    ledger_id: str
    invited_account_id: int
    invited_device_id: int
    invited_membership_id: int
    invited_session_hash: str
    transitive_account_id: int
    transitive_device_id: int
    transitive_membership_id: int
    transitive_session_hash: str
    transitive_pending_invite_token: str
    cross_ledger_id: str
    cross_account_id: int
    cross_device_id: int
    cross_membership_id: int
    cross_session_hash: str
    unrelated_account_id: int
    unrelated_device_id: int
    unrelated_membership_id: int
    unrelated_session_hash: str


def _accept_exposure_window_member(
    client: TestClient,
    *,
    owner_session_token: str,
    db: Session,
) -> _MemberEvidence:
    invitation = client.post(
        "/api/ledgers/owner/invitations",
        headers={"Authorization": f"Bearer {owner_session_token}"},
        json={"role": "member", "ttl_days": 7},
    )
    assert invitation.status_code == 201, invitation.text
    return _accept_invitation_token(
        client,
        invite_token=invitation.json()["invite_token"],
        account_name="Exposure Window Member",
        device_name="Exposure Window Member Device",
        db=db,
    )


def _accept_invitation_token(
    client: TestClient,
    *,
    invite_token: str,
    account_name: str,
    device_name: str,
    db: Session,
) -> _MemberEvidence:
    accepted = client.post(
        "/api/invitations/accept",
        json={
            "invite_token": invite_token,
            "account_name": account_name,
            "device_name": device_name,
            "platform": "android",
        },
    )
    assert accepted.status_code == 200, accepted.text
    session_hash = hash_secret(accepted.json()["session_token"])
    session = db.query(AuthToken).filter(AuthToken.token_hash == session_hash).one()
    membership = db.query(LedgerMember).filter(
        LedgerMember.ledger_id == session.ledger_id,
        LedgerMember.account_id == session.account_id,
    ).one()
    return _MemberEvidence(
        account_id=session.account_id,
        device_id=session.device_id,
        membership_id=membership.id,
        session_hash=session_hash,
    )


def _seed_cross_ledger_descendant(
    client: TestClient,
    *,
    db: Session,
    bootstrap_account_id: int,
) -> tuple[str, _MemberEvidence]:
    ledger_id = "bootstrap-exposure-cross-ledger"
    db.add(
        Ledger(
            ledger_id=ledger_id,
            name="Exposure Cross Ledger",
            owner_account_id=bootstrap_account_id,
        )
    )
    db.flush()
    db.add(
        LedgerMember(
            ledger_id=ledger_id,
            account_id=bootstrap_account_id,
            role="owner",
        )
    )
    db.commit()
    invitation = invitation_invites.create_invitation(
        db,
        ledger_id=ledger_id,
        role="member",
        created_by_account_id=bootstrap_account_id,
    )
    accepted = _accept_invitation_token(
        client,
        invite_token=invitation.invite_token,
        account_name="Cross Ledger Descendant",
        device_name="Cross Ledger Descendant Device",
        db=db,
    )
    return ledger_id, accepted


def _seed_transitive_descendant(
    client: TestClient,
    *,
    db: Session,
    ledger_id: str,
    first_generation_account_id: int,
) -> tuple[_MemberEvidence, str]:
    used_invitation = invitation_invites.create_invitation(
        db,
        ledger_id=ledger_id,
        role="member",
        created_by_account_id=first_generation_account_id,
    )
    accepted = _accept_invitation_token(
        client,
        invite_token=used_invitation.invite_token,
        account_name="Transitive Descendant",
        device_name="Transitive Descendant Device",
        db=db,
    )
    pending_invitation = invitation_invites.create_invitation(
        db,
        ledger_id=ledger_id,
        role="viewer",
        created_by_account_id=first_generation_account_id,
    )
    return accepted, pending_invitation.invite_token


def _seed_unrelated_same_ledger_member(db: Session, *, ledger_id: str) -> _MemberEvidence:
    account = Account(display_name="Unrelated Same-Ledger Member")
    db.add(account)
    db.flush()
    membership = LedgerMember(ledger_id=ledger_id, account_id=account.id, role="member")
    device = Device(
        account_id=account.id,
        device_name="Unrelated Device",
        platform="android",
    )
    db.add_all((membership, device))
    db.flush()
    session_hash = hash_secret("unrelated-same-ledger-session")
    db.add(
        AuthToken(
            token_hash=session_hash,
            account_id=account.id,
            device_id=device.id,
            ledger_id=ledger_id,
            scope="app",
        )
    )
    evidence = _MemberEvidence(
        account_id=account.id,
        device_id=device.id,
        membership_id=membership.id,
        session_hash=session_hash,
    )
    db.commit()
    return evidence


def _bootstrap_and_pair_owner(
    client: TestClient,
    db: Session,
) -> tuple[str, PairingCode]:
    initial = _post_bootstrap(
        client,
        secret=_VECTOR_SECRET,
        body={
            "account_name": "Vector Owner",
            "ledger_name": "Vector Ledger",
            "device_name": "Vector Windows",
        },
    )
    assert initial.status_code == 200, initial.text
    stale_pairing = db.query(PairingCode).filter(
        PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
    ).one()
    paired = client.post(
        "/api/auth/pair",
        json={
            "pairing_code": _VECTOR_PAIRING_CODE,
            "device_name": "Exposure Window Device",
            "platform": "android",
        },
    )
    assert paired.status_code == 200, paired.text
    return paired.json()["session_token"], stale_pairing


def _seed_exposure_records(
    client: TestClient,
    *,
    db: Session,
    owner_session_token: str,
    stale_pairing: PairingCode,
) -> _ExposureWindow:
    invited = _accept_exposure_window_member(
        client,
        owner_session_token=owner_session_token,
        db=db,
    )
    invited_session = db.query(AuthToken).filter(
        AuthToken.token_hash == invited.session_hash
    ).one()
    bootstrap_membership = db.query(LedgerMember).filter(
        LedgerMember.ledger_id == invited_session.ledger_id,
        LedgerMember.role == "owner",
    ).one()
    unrelated = _seed_unrelated_same_ledger_member(db, ledger_id=invited_session.ledger_id)
    cross_ledger_id, cross = _seed_cross_ledger_descendant(
        client,
        db=db,
        bootstrap_account_id=bootstrap_membership.account_id,
    )
    exposed_invitation = client.post(
        "/api/ledgers/owner/invitations",
        headers={"Authorization": f"Bearer {owner_session_token}"},
        json={"role": "member", "ttl_days": 7},
    )
    assert exposed_invitation.status_code == 201, exposed_invitation.text
    transferred = client.post(
        f"/api/ledgers/{invited_session.ledger_id}/members/{invited.membership_id}/transfer-owner",
        headers={"Authorization": f"Bearer {owner_session_token}"},
    )
    assert transferred.status_code == 200, transferred.text
    db.expire_all()
    transitive, transitive_pending_invite_token = _seed_transitive_descendant(
        client,
        db=db,
        ledger_id=invited_session.ledger_id,
        first_generation_account_id=invited.account_id,
    )
    return _ExposureWindow(
        stale_pairing_session=db,
        stale_pairing_id=stale_pairing.id,
        stale_pairing_hash=stale_pairing.code_hash,
        exposed_session_hash=hash_secret(owner_session_token),
        exposed_invite_token=exposed_invitation.json()["invite_token"],
        bootstrap_account_id=bootstrap_membership.account_id,
        bootstrap_membership_id=bootstrap_membership.id,
        ledger_id=invited_session.ledger_id,
        invited_account_id=invited.account_id,
        invited_device_id=invited.device_id,
        invited_membership_id=invited.membership_id,
        invited_session_hash=invited.session_hash,
        transitive_account_id=transitive.account_id,
        transitive_device_id=transitive.device_id,
        transitive_membership_id=transitive.membership_id,
        transitive_session_hash=transitive.session_hash,
        transitive_pending_invite_token=transitive_pending_invite_token,
        cross_ledger_id=cross_ledger_id,
        cross_account_id=cross.account_id,
        cross_device_id=cross.device_id,
        cross_membership_id=cross.membership_id,
        cross_session_hash=cross.session_hash,
        unrelated_account_id=unrelated.account_id,
        unrelated_device_id=unrelated.device_id,
        unrelated_membership_id=unrelated.membership_id,
        unrelated_session_hash=unrelated.session_hash,
    )


def _open_exposure_window(monkeypatch: pytest.MonkeyPatch) -> _ExposureWindow:
    # Reproduce state an older vulnerable runtime could have committed before
    # the sensitive-mutation guards existed.
    monkeypatch.setattr(
        invitation_invites,
        "assert_bootstrap_sensitive_mutation_allowed",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        invitation_members,
        "assert_bootstrap_sensitive_mutation_allowed",
        lambda *args, **kwargs: None,
    )
    with TestClient(app) as client:
        db = SessionLocal()
        keep_session = False
        try:
            owner_session_token, stale_pairing = _bootstrap_and_pair_owner(client, db)
            exposure = _seed_exposure_records(
                client,
                db=db,
                owner_session_token=owner_session_token,
                stale_pairing=stale_pairing,
            )
            keep_session = True
            return exposure
        finally:
            if not keep_session:
                db.close()


def _expire_exposed_upload_link() -> None:
    with SessionLocal() as db:
        exposed_upload = db.query(UploadLink).filter(
            UploadLink.token_hash == hash_secret(_VECTOR_UPLOAD_KEY)
        ).one()
        exposed_upload.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()


def _seed_historical_revocation_evidence(exposure: _ExposureWindow) -> datetime:
    historical_at = now_utc() - timedelta(days=3)
    with SessionLocal() as db:
        exposed_session = db.query(AuthToken).filter(
            AuthToken.token_hash == exposure.exposed_session_hash
        ).one()
        exposed_session.revoked_at = historical_at
        exposed_session.grace_until = now_utc() + timedelta(hours=1)
        exposed_device = db.get(Device, exposed_session.device_id)
        invited_account = db.get(Account, exposure.invited_account_id)
        invited_device = db.get(Device, exposure.invited_device_id)
        invited_membership = db.get(LedgerMember, exposure.invited_membership_id)
        assert exposed_device is not None
        assert invited_account is not None
        assert invited_device is not None
        assert invited_membership is not None
        exposed_device.revoked_at = historical_at
        invited_account.disabled_at = historical_at
        invited_device.revoked_at = historical_at
        invited_membership.disabled_at = historical_at
        db.commit()
    return historical_at

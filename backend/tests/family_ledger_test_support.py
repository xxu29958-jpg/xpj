"""Real ledger, invitation and session setup shared by API and Web consumers."""

from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Ledger, LedgerMember
from app.services.identity_service import hash_secret
from app.services.invitation_service import create_invitation
from app.services.ledger_calendar_service import adopt_ledger_calendar
from app.services.time_service import now_utc
from tests._runtime_protocol import current_protocol_headers


def _create_family_ledger(client: TestClient, name: str = "家庭账本", *, identity) -> str:
    """Use admin token to mint a new ledger; owner-account is auto-added."""
    resp = client.post("/api/ledgers", headers=identity.admin_headers, json={"name": name})
    assert resp.status_code == 201, resp.json()
    return resp.json()["ledger_id"]


def _switch_to(client: TestClient, ledger_id: str, headers: dict[str, str]) -> str:
    resp = client.post(f"/api/ledgers/{ledger_id}/switch", headers=headers)
    assert resp.status_code == 200, resp.json()
    return resp.json()["session_token"]


def _bearer(token: str) -> dict[str, str]:
    return current_protocol_headers({"Authorization": f"Bearer {token}"})


def _prepare_existing_session_invitation(token: str) -> tuple[datetime, int, tuple[int, int, int]]:
    with SessionLocal() as db:
        token_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert token_row is not None
        expected_expiry = now_utc() + timedelta(days=12)
        token_row.expires_at = expected_expiry
        db.commit()
        return expected_expiry, token_row.account_id, _identity_row_counts(db)


def _identity_row_counts(db: Session) -> tuple[int, int, int]:
    return (
        db.scalar(select(func.count()).select_from(Account)),
        db.scalar(select(func.count()).select_from(Device)),
        db.scalar(select(func.count()).select_from(AuthToken)),
    )


def _assert_existing_session_invitation_rows(
    *,
    family_id: str,
    account_id: int,
    token: str,
    counts_before: tuple[int, int, int],
) -> None:
    with SessionLocal() as db:
        assert _identity_row_counts(db) == counts_before
        membership = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == family_id).where(LedgerMember.account_id == account_id)
        )
        assert membership is not None and membership.role == "member"
        token_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert token_row is not None and token_row.ledger_id == family_id


def _mint_foreign_ledger_invitation(role: str = "member") -> tuple[str, str]:
    ledger_id = f"foreign_{uuid4().hex[:12]}"
    with SessionLocal() as db:
        owner = Account(display_name="另一家庭的拥有者")
        db.add(owner)
        db.flush()
        db.add(
            Ledger(
                ledger_id=ledger_id,
                name="另一家庭账本",
                owner_account_id=owner.id,
            )
        )
        db.add(LedgerMember(ledger_id=ledger_id, account_id=owner.id, role="owner"))
        db.flush()
        adopt_ledger_calendar(db, ledger_id=ledger_id, timezone_name="Asia/Shanghai")
        invitation = create_invitation(
            db,
            ledger_id=ledger_id,
            role=role,
            note=None,
            created_by_account_id=owner.id,
            auth=None,
        )
    return ledger_id, invitation.invite_token


def set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def demote_owner_ledger_members_to_viewer() -> None:
    with SessionLocal() as db:
        members = db.scalars(select(LedgerMember).where(LedgerMember.ledger_id == "owner")).all()
        assert members
        for member in members:
            member.role = "viewer"
        db.commit()

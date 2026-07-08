"""Regression tests for batched short-secret allocators."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

import app.services.admin_service._upload_links as upload_link_service
import app.services.identity_service._device as identity_device
import app.services.invitation_invites as invitation_invites
from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, Device, Invitation, PairingCode, UploadLink
from app.services.identity_service import hash_pairing_code, hash_secret
from app.services.time_service import now_utc


def _patch_sequence(monkeypatch: pytest.MonkeyPatch, target: object, name: str, values: list[str]) -> None:
    generated = iter(values)
    monkeypatch.setattr(target, name, lambda *args, **kwargs: next(generated))


def _seed_pairing_collision(account_id: int) -> None:
    with SessionLocal() as db:
        db.add(
            PairingCode(
                code_hash=hash_pairing_code("11111111"),
                ledger_id="owner",
                account_id=account_id,
                expires_at=now_utc() + timedelta(minutes=15),
            )
        )
        db.commit()


def _assert_pairing_allocator(monkeypatch: pytest.MonkeyPatch, account_id: int) -> None:
    _seed_pairing_collision(account_id)
    values = ["11111111", "22222222"] + [
        str(33333330 + index) for index in range(identity_device.PAIRING_CODE_CANDIDATE_COUNT - 2)
    ]
    _patch_sequence(monkeypatch, identity_device, "new_pairing_code", values)
    with SessionLocal() as db:
        assert identity_device._new_unique_pairing_code(db)[0] == "22222222"

    collisions = [str(70000000 + index) for index in range(identity_device.PAIRING_CODE_CANDIDATE_COUNT)]
    with SessionLocal() as db:
        db.add_all(
            PairingCode(
                code_hash=hash_pairing_code(code),
                ledger_id="owner",
                account_id=account_id,
                expires_at=now_utc() + timedelta(minutes=15),
            )
            for code in collisions
        )
        db.flush()
        _patch_sequence(monkeypatch, identity_device, "new_pairing_code", collisions)
        with pytest.raises(AppError):
            identity_device._new_unique_pairing_code(db)


def _assert_invitation_allocator(monkeypatch: pytest.MonkeyPatch, account_id: int) -> None:
    with SessionLocal() as db:
        db.add(
            Invitation(
                ledger_id="owner",
                token_hash=hash_secret("inv_taken"),
                role="member",
                created_by_account_id=account_id,
                expires_at=now_utc() + timedelta(days=7),
            )
        )
        db.flush()
        values = ["inv_taken", "inv_free"] + [
            f"inv_unused_{index}" for index in range(invitation_invites.INVITATION_TOKEN_CANDIDATE_COUNT - 2)
        ]
        _patch_sequence(monkeypatch, invitation_invites, "new_invite_token", values)
        assert invitation_invites._new_unique_invite_token(db)[0] == "inv_free"

    collisions = [
        f"inv_colliding_{index}" for index in range(invitation_invites.INVITATION_TOKEN_CANDIDATE_COUNT)
    ]
    with SessionLocal() as db:
        db.add_all(
            Invitation(
                ledger_id="owner",
                token_hash=hash_secret(token),
                role="member",
                created_by_account_id=account_id,
                expires_at=now_utc() + timedelta(days=7),
            )
            for token in collisions
        )
        db.flush()
        _patch_sequence(monkeypatch, invitation_invites, "new_invite_token", collisions)
        with pytest.raises(AppError):
            invitation_invites._new_unique_invite_token(db)


def _assert_upload_public_id_allocator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account_id: int,
    device_id: int,
) -> None:
    with SessionLocal() as db:
        db.add(
            UploadLink(
                public_id="upload_taken",
                token_hash=hash_secret("upload_public_taken"),
                account_id=account_id,
                device_id=device_id,
                ledger_id="owner",
                expires_at=now_utc() + timedelta(days=7),
            )
        )
        db.flush()
        values = ["upload_taken", "upload_free"] + [
            f"upload_unused_{index}"
            for index in range(upload_link_service.UPLOAD_LINK_PUBLIC_ID_CANDIDATE_COUNT - 2)
        ]
        _patch_sequence(monkeypatch, uuid, "uuid4", values)
        assert upload_link_service._new_public_id(db) == "upload_free"

    collisions = [
        f"upload_collide_{index}" for index in range(upload_link_service.UPLOAD_LINK_PUBLIC_ID_CANDIDATE_COUNT)
    ]
    with SessionLocal() as db:
        db.add_all(
            UploadLink(
                public_id=public_id,
                token_hash=hash_secret(f"{public_id}_token"),
                account_id=account_id,
                device_id=device_id,
                ledger_id="owner",
                expires_at=now_utc() + timedelta(days=7),
            )
            for public_id in collisions
        )
        db.flush()
        _patch_sequence(monkeypatch, uuid, "uuid4", collisions)
        with pytest.raises(AppError):
            upload_link_service._new_public_id(db)


def test_batched_short_secret_allocators_skip_collisions_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    with SessionLocal() as db:
        account_id = db.scalar(select(Account.id).order_by(Account.id.asc()))
        device_id = db.scalar(select(Device.id).order_by(Device.id.asc()))
    assert account_id is not None
    assert device_id is not None

    _assert_pairing_allocator(monkeypatch, account_id)
    _assert_invitation_allocator(monkeypatch, account_id)
    _assert_upload_public_id_allocator(monkeypatch, account_id=account_id, device_id=device_id)

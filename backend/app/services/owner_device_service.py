"""Owner-facing device management (issue #65 slice 6a).

The shared ``admin_service._devices`` functions back the loopback ``/owner``
console and the loopback ``/api/admin/*`` routes. This module wraps them for the
account owner's app-token ``/api/ledgers/{ledger_id}/devices`` routes (Slice 6):

* every operation is scoped to the owner's active ledger (``ledger_ids`` filter)
  so a device is only visible / mutable if it has a token or upload-link in THAT
  ledger. This is ledger-admin authority, not account-ownership: an owner can
  revoke ANOTHER member's device's access to their ledger (correct — a ledger
  owner controls who reaches their ledger), but the revoke is contained to this
  ledger and never reaches a device's tokens in ledgers the caller doesn't own;
* it marks which row is the caller's OWN device (``is_current``) so the client
  can hide the self-revoke affordance;
* it gives owner-appropriate copy for the self-revoke guard (the shared admin
  copy mentions admin-only local scripts, §10 jargon for a normal owner).

Permission is enforced by the route's ``get_current_member_manager_context``
guard (app token, path-ledger-bound, owner role) — viewers/members get 403.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import admin_service
from app.services.admin_service._dtos import DeviceSummary
from app.services.identity_service import PairingCodeResult, create_pairing_code
from app.tenants import AuthContext


@dataclass(frozen=True)
class MyDevice:
    summary: DeviceSummary
    is_current: bool


def _ledger_scope(auth: AuthContext) -> set[str]:
    return {auth.ledger_id}


def _current_public_id(db: Session, auth: AuthContext) -> str:
    return admin_service.device_public_id(db, auth.device_id)


def _as_my_device(summary: DeviceSummary, current_public_id: str) -> MyDevice:
    return MyDevice(summary=summary, is_current=summary.public_id == current_public_id)


def list_my_devices(db: Session, auth: AuthContext) -> list[MyDevice]:
    current = _current_public_id(db, auth)
    summaries = admin_service.list_devices(db, ledger_ids=_ledger_scope(auth))
    return [_as_my_device(s, current) for s in summaries]


def rename_my_device(db: Session, auth: AuthContext, *, public_id: str, new_name: str) -> MyDevice:
    summary = admin_service.rename_device(
        db, public_id=public_id, new_name=new_name, ledger_ids=_ledger_scope(auth)
    )
    return _as_my_device(summary, _current_public_id(db, auth))


def revoke_my_device(db: Session, auth: AuthContext, *, public_id: str) -> MyDevice:
    current = _current_public_id(db, auth)
    if public_id == current:
        # Owner copy for the self-revoke guard (the shared admin_service copy
        # talks about local admin scripts). Revoking the device you're on would
        # log you out mid-action; do it from another device or sign out.
        raise AppError(
            "invalid_request",
            "不能停用当前正在使用的设备。请在另一台设备上操作，或直接退出登录。",
            status_code=409,
        )
    summary = admin_service.revoke_device(
        db,
        public_id=public_id,
        current_device_public_id=current,
        ledger_ids=_ledger_scope(auth),
    )
    return _as_my_device(summary, current)


def create_my_pairing_code(
    db: Session, auth: AuthContext, *, device_name_hint: str | None, ttl_minutes: int
) -> PairingCodeResult:
    return create_pairing_code(
        db,
        ledger_id=auth.ledger_id,
        account_id=auth.account_id,
        device_name_hint=device_name_hint,
        ttl_minutes=ttl_minutes,
    )

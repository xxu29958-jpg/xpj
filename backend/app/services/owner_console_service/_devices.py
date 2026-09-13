"""Owner Console device management for the canonical local owner Account."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.admin_service import (
    DeviceSummary,
    delete_device,
    list_devices,
    rename_device,
    revoke_device,
)
from app.services.identity_service import live_web_device_public_ids
from app.services.owner_console_service._ledger_console import _require_owner_id

__all__ = [
    "DeviceSummary",
    "do_delete_device",
    "do_rename_device",
    "do_revoke_device",
    "get_devices",
]


@dataclass(frozen=True)
class ConsoleDeviceInventory:
    devices: list[DeviceSummary]
    ended_browser_sessions: list[DeviceSummary]

    @property
    def active_device_count(self) -> int:
        return sum(device.revoked_at is None for device in self.devices)


def get_devices(db: Session) -> ConsoleDeviceInventory:
    account_id = _require_owner_id(db)
    live_browsers = live_web_device_public_ids(db, account_id=account_id)
    devices: list[DeviceSummary] = []
    history: list[DeviceSummary] = []
    for device in list_devices(db, account_id=account_id):
        target = (
            history
            if device.platform == "web" and device.public_id not in live_browsers
            else devices
        )
        target.append(device)
    return ConsoleDeviceInventory(devices=devices, ended_browser_sessions=history)


def do_revoke_device(db: Session, public_id: str, current_device_public_id: str) -> DeviceSummary:
    return revoke_device(
        db,
        public_id=public_id,
        current_device_public_id=current_device_public_id,
        auth=None,
        actor_account_id=_require_owner_id(db),
    )


def do_delete_device(db: Session, public_id: str, current_device_public_id: str) -> None:
    delete_device(
        db,
        public_id=public_id,
        current_device_public_id=current_device_public_id,
        auth=None,
        actor_account_id=_require_owner_id(db),
    )


def do_rename_device(db: Session, public_id: str, new_name: str) -> DeviceSummary:
    return rename_device(
        db,
        public_id=public_id,
        new_name=new_name,
        auth=None,
        actor_account_id=_require_owner_id(db),
    )

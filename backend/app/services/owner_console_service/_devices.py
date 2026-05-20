"""Owner Console device management — thin wrappers over admin_service that
scope every operation to the local owner's managed ledger set."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.admin_service import (
    DeviceSummary,
    delete_device,
    list_devices,
    rename_device,
    revoke_device,
)
from app.services.owner_console_service._ledger_console import (
    _managed_console_ledger_ids,
)


__all__ = [
    "DeviceSummary",
    "do_delete_device",
    "do_rename_device",
    "do_revoke_device",
    "get_devices",
]


def get_devices(db: Session) -> list[DeviceSummary]:
    return list_devices(db, ledger_ids=_managed_console_ledger_ids(db))


def do_revoke_device(db: Session, public_id: str, current_device_public_id: str) -> DeviceSummary:
    return revoke_device(
        db,
        public_id=public_id,
        current_device_public_id=current_device_public_id,
        ledger_ids=_managed_console_ledger_ids(db),
    )


def do_delete_device(db: Session, public_id: str, current_device_public_id: str) -> None:
    delete_device(
        db,
        public_id=public_id,
        current_device_public_id=current_device_public_id,
        ledger_ids=_managed_console_ledger_ids(db),
    )


def do_rename_device(db: Session, public_id: str, new_name: str) -> DeviceSummary:
    return rename_device(
        db,
        public_id=public_id,
        new_name=new_name,
        ledger_ids=_managed_console_ledger_ids(db),
    )

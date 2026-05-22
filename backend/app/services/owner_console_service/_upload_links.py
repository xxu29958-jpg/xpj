"""Owner Console upload-link management.

Same shape as ``_devices``: every public function looks up the managed
ledger set first, then delegates to ``admin_service``. The
``compose_public_upload_url`` helper is local because it also reads
``PUBLIC_BASE_URL`` from app config.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.admin_service import (
    UploadLinkSecret,
    UploadLinkSummary,
    create_upload_link,
    delete_upload_link,
    list_upload_links,
    revoke_upload_link,
    rotate_upload_link,
)
from app.services.owner_console_service._ledger_console import (
    _managed_console_ledger_ids,
)

__all__ = [
    "UploadLinkSecret",
    "UploadLinkSummary",
    "compose_public_upload_url",
    "do_create_upload_link",
    "do_delete_upload_link",
    "do_revoke_upload_link",
    "do_rotate_upload_link",
    "get_upload_links",
]


def get_upload_links(db: Session) -> list[UploadLinkSummary]:
    managed_ids = _managed_console_ledger_ids(db)
    if not managed_ids:
        return []
    return list_upload_links(db, ledger_ids=managed_ids)


def do_create_upload_link(
    db: Session, *, ledger_id: str, admin_account_id: int, default_timezone: str
) -> tuple[UploadLinkSummary, UploadLinkSecret]:
    return create_upload_link(
        db,
        ledger_id=ledger_id,
        admin_account_id=admin_account_id,
        default_timezone=default_timezone,
        ledger_ids=_managed_console_ledger_ids(db),
    )


def do_rotate_upload_link(db: Session, public_id: str) -> tuple[UploadLinkSummary, UploadLinkSecret]:
    return rotate_upload_link(
        db,
        public_id=public_id,
        ledger_ids=_managed_console_ledger_ids(db),
    )


def do_revoke_upload_link(db: Session, public_id: str) -> UploadLinkSummary:
    return revoke_upload_link(
        db,
        public_id=public_id,
        ledger_ids=_managed_console_ledger_ids(db),
    )


def do_delete_upload_link(db: Session, public_id: str) -> None:
    delete_upload_link(
        db,
        public_id=public_id,
        ledger_ids=_managed_console_ledger_ids(db),
    )


def compose_public_upload_url(secret: UploadLinkSecret) -> str | None:
    """Return the absolute public URL for an UploadLink secret.

    Combines :envvar:`PUBLIC_BASE_URL` with the relative ``upload_url_path``
    produced by :mod:`app.services.admin_service`. Returns ``None`` when
    ``PUBLIC_BASE_URL`` is not configured so the caller can render a
    configuration hint instead of a half-broken URL.

    The relative path already includes ``?tz=...``; do not append it again.
    Never log or persist the returned value.
    """
    cfg = get_settings()
    base = (cfg.public_base_url or "").rstrip("/")
    if not base:
        return None
    return base + secret.upload_url_path

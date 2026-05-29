"""Admin service helpers for v0.3.1-alpha2 device & UploadLink management.

These helpers are called from :mod:`app.routes.admin`. They never return raw
secrets except for newly minted upload keys (which is the one-shot reveal flow
that the contract explicitly allows when creating or rotating a link).

Important guarantees:

* The current admin's own device cannot be revoked by accident — the caller
  must enforce that. The service raises if the public id is unknown or already
  revoked.
* Revoking a device atomically revokes every active ``AuthToken`` and
  ``UploadLink`` for that device.
* Rotating an upload link revokes the old link and returns the new key once.

The implementation lives in two private sub-modules (``_devices`` and
``_upload_links``) plus a shared ``_dtos`` module; this package re-exports
the full public surface so callers keep importing from
``app.services.admin_service``.
"""

from __future__ import annotations

from app.services.admin_service._devices import (
    DeviceCleanupResult,
    cleanup_revoked_devices,
    delete_device,
    device_public_id,
    list_devices,
    rename_device,
    revoke_device,
)
from app.services.admin_service._dtos import (
    DeviceSummary,
    UploadLinkSecret,
    UploadLinkSummary,
)
from app.services.admin_service._upload_links import (
    create_upload_link,
    delete_upload_link,
    extend_upload_link,
    list_upload_links,
    revoke_upload_link,
    rotate_upload_link,
    update_upload_link_limits,
)

__all__ = [
    "DeviceSummary",
    "DeviceCleanupResult",
    "UploadLinkSecret",
    "UploadLinkSummary",
    "cleanup_revoked_devices",
    "create_upload_link",
    "delete_device",
    "device_public_id",
    "delete_upload_link",
    "extend_upload_link",
    "list_devices",
    "list_upload_links",
    "rename_device",
    "revoke_device",
    "revoke_upload_link",
    "rotate_upload_link",
    "update_upload_link_limits",
]

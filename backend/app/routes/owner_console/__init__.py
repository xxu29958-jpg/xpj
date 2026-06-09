"""Owner Console routes — local-only HTML admin UI.

All endpoints check that the request comes from the loopback address
(127.0.0.1 or ::1). Remote or Cloudflare-forwarded requests are rejected with
403. This is *not* a public admin backend.

The package mounts seven sub-routers (one per UI section); each holds an
APIRouter with the ``/owner`` prefix so the operation IDs stay rooted at
the same path-segment they did before the split.

Navigation:
    GET  /owner                     — dashboard / index
    GET  /owner/rule-applications   — read-only rule batch audit overview
    GET  /owner/devices             — device list
    POST /owner/devices/{id}/revoke — revoke device
    POST /owner/devices/{id}/rename — rename device
    POST /owner/devices/{id}/delete — delete device
    GET  /owner/pairing             — generate pairing code
    POST /owner/pairing             — create and display new code
    GET  /owner/upload-links        — upload link list
    POST /owner/upload-links        — create new upload link
    POST /owner/upload-links/{id}/rotate  — rotate key (one-shot reveal)
    POST /owner/upload-links/{id}/revoke  — revoke link
    POST /owner/upload-links/{id}/delete  — delete link
    GET  /owner/diagnostics         — diagnostics page
    GET  /owner/fx                  — FX rate sync status + latest rates
    POST /owner/fx/refresh          — run one FX sync now (manual trigger)
    GET  /owner/settings(/*)        — runtime settings (5 endpoints)
    GET  /owner/backups             — list manual backups
    POST /owner/backups             — create new manual backup
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routes.owner_console import (
    _ai_advisor,
    _algorithm_versions,
    _backups,
    _devices,
    _diagnostics,
    _fx,
    _index,
    _learning_maintenance,
    _pairing,
    _settings,
    _tag_cleanup,
    _upload_links,
)
from app.routes.owner_console._shared import (
    LocalOnly,
    _base,
    _format_owner_datetime,
    _require_local,
    logger,
    templates,
)

router = APIRouter()
router.include_router(_index.router)
router.include_router(_ai_advisor.router)
router.include_router(_algorithm_versions.router)
router.include_router(_learning_maintenance.router)
router.include_router(_tag_cleanup.router)
router.include_router(_devices.router)
router.include_router(_pairing.router)
router.include_router(_upload_links.router)
router.include_router(_diagnostics.router)
router.include_router(_fx.router)
router.include_router(_settings.router)
router.include_router(_backups.router)


__all__ = [
    "LocalOnly",
    "_base",
    "_format_owner_datetime",
    "_require_local",
    "logger",
    "router",
    "templates",
]

"""Centralized version constants for the backend.

Update :data:`BACKEND_VERSION` here when releasing a new version. All other
modules — FastAPI app metadata, ``/api/health``, README, scripts — should read
from this constant rather than duplicating the literal string.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

BACKEND_VERSION = "1.2.0"

_ASSET_VERSION_ENV = "XPJ_STATIC_ASSET_VERSION"
_ASSET_TREE_DIRS = ("app/static", "app/templates")


def _asset_tree_fingerprint(backend_root: Path) -> str:
    digest = hashlib.sha256()
    has_assets = False
    for relative_dir in _ASSET_TREE_DIRS:
        asset_dir = backend_root / relative_dir
        if not asset_dir.exists():
            continue
        for asset_path in sorted(path for path in asset_dir.rglob("*") if path.is_file()):
            try:
                asset_bytes = asset_path.read_bytes()
            except OSError:
                continue
            has_assets = True
            digest.update(asset_path.relative_to(backend_root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(asset_bytes)
            digest.update(b"\0")
    return digest.hexdigest()[:12] if has_assets else "source"


def _resolve_static_asset_version(backend_root: Path) -> str:
    explicit = os.environ.get(_ASSET_VERSION_ENV, "").strip()
    if explicit:
        return explicit
    return f"{BACKEND_VERSION}-{_asset_tree_fingerprint(backend_root)}"


STATIC_ASSET_VERSION = _resolve_static_asset_version(Path(__file__).resolve().parents[1])

# Identity model schema version. Bumped when the Account / Ledger / Device /
# AuthToken / UploadLink / PairingCode contract changes in a way clients must
# notice. v0.3 is the current identity schema; v0.3.1 hardens HTTP bootstrap
# and stops auto-moving uploads but does not change the identity tables.
IDENTITY_SCHEMA_VERSION = "v0.3"

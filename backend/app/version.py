"""Centralized version constants for the backend.

Update :data:`BACKEND_VERSION` here when releasing a new version. All other
modules — FastAPI app metadata, ``/api/health``, README, scripts — should read
from this constant rather than duplicating the literal string.
"""

from __future__ import annotations

BACKEND_VERSION = "1.0.0"

# Identity model schema version. Bumped when the Account / Ledger / Device /
# AuthToken / UploadLink / PairingCode contract changes in a way clients must
# notice. v0.3 is the current identity schema; v0.3.1 hardens HTTP bootstrap
# and stops auto-moving uploads but does not change the identity tables.
IDENTITY_SCHEMA_VERSION = "v0.3"

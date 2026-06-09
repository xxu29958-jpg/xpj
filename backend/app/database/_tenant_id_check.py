"""Cross-dialect tenant_id format validation.

Used by identity seeding (:mod:`app.database._seed`) and the legacy
upload-path migration (:mod:`app.database._uploads`) to reject legacy rows
whose ``tenant_id`` does not match the supported pattern. This runs on every
engine — it is NOT SQLite-only machinery — so it lives outside the retired
``_validate`` package.
"""

from __future__ import annotations

import re

from app.errors import DataIntegrityError


def _tenant_id_pattern():
    # Imported lazily so this module stays a leaf of the dependency graph
    # (app.tenants pulls in config / errors but not the database package).
    from app.tenants import TENANT_ID_PATTERN

    return TENANT_ID_PATTERN


def _validate_legacy_tenant_ids(tenant_ids: set[str], *, source: str) -> None:
    pattern: re.Pattern[str] = _tenant_id_pattern()
    invalid = sorted(tenant_id for tenant_id in tenant_ids if not pattern.fullmatch(tenant_id))
    if invalid:
        sample = ", ".join(invalid[:3])
        raise DataIntegrityError(f"Invalid legacy data: {source} contains unsupported tenant_id values: {sample}")

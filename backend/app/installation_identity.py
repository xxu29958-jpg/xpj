"""Resolve the backend instance identity from one explicit data-root input."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import UUID

_SOURCE_ID_NAMESPACE = b"ticketbox-installation-v1\0"


def installation_identity(data_root: Path) -> str:
    """Return the installed binding UUID, or a deterministic source identity."""

    explicit = os.environ.get("TICKETBOX_INSTALLATION_ID", "").strip().lower()
    if explicit:
        try:
            canonical = str(UUID(explicit))
        except ValueError as exc:
            raise ValueError("TICKETBOX_INSTALLATION_ID must be a canonical UUID") from exc
        if canonical != explicit:
            raise ValueError("TICKETBOX_INSTALLATION_ID must be a canonical UUID")
        return canonical

    normalized_root = os.path.normcase(str(data_root.resolve())).encode("utf-8")
    digest = hashlib.sha256(_SOURCE_ID_NAMESPACE + normalized_root).hexdigest()
    return f"ticketbox-{digest[:32]}"


__all__ = ["installation_identity"]

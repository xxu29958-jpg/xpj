"""Read-only build labels for existing logs; fingerprints are not Git SHAs."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from functools import cache
from pathlib import Path

from app.version import BACKEND_VERSION


@cache
def diagnostic_build_identity() -> str:
    if getattr(sys, "frozen", False):
        manifest = Path(sys.executable).parent / "BUILD_PROVENANCE.json"
        try:
            with manifest.open("rb") as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
            value = json.loads(raw) if len(raw) <= 2 * 1024 * 1024 else None
            if isinstance(value, dict) and value.get("artifact_type") == "ticketbox-frozen-backend":
                source = value.get("source", {}).get("fingerprint")
                payload = value.get("payload", {}).get("fingerprint")
                if all(isinstance(item, str) and re.fullmatch(r"[0-9a-f]{64}", item) for item in (source, payload)):
                    return f"version={BACKEND_VERSION} recorded_source_sha256={source} recorded_payload_sha256={payload}"
        except (OSError, ValueError, AttributeError):
            pass
        return f"version={BACKEND_VERSION} build_identity=manifest_unavailable"

    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    try:
        for path in sorted([*(root / "app").rglob("*.py"), root / "packaging/launch.py"]):
            digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes() + b"\0")
    except OSError:
        return f"version={BACKEND_VERSION} build_identity=source_unreadable"
    return f"version={BACKEND_VERSION} source_tree_sha256={digest.hexdigest()}"

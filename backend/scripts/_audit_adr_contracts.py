"""Release-audit lane for executable ADR contracts and generated views."""

from __future__ import annotations

import sys

from adr_contract_ratchet import audit_base_ratchets
from adr_contract_registry import RegistryError, build_registry
from adr_contract_views import stale_view_errors


def validate() -> list[str]:
    """Return every contract-registry error without mutating the worktree."""

    try:
        registry = build_registry()
        ratchet = audit_base_ratchets(registry)
        for notice in ratchet.notices:
            print(f"INFO: {notice}")
        return [*stale_view_errors(registry), *ratchet.errors]
    except (OSError, RegistryError) as exc:
        return [str(exc)]


def main() -> int:
    errors = validate()
    if errors:
        print("FAIL: executable ADR contract registry")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("PASS: ADR front matter, legacy ratchet, registry, index, status, and graph agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())

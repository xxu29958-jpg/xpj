"""Explicitly regenerate deterministic ADR registry views."""

from __future__ import annotations

from adr_contract_registry import build_registry
from adr_contract_views import write_views


def main() -> None:
    registry = build_registry()
    write_views(registry)
    print(
        f"Rendered {len(registry.entries)} ADRs from front matter + "
        "legacy history/calibration"
    )


if __name__ == "__main__":
    main()

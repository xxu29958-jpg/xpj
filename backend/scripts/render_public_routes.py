"""Render reviewed route docs and example remote ingress (never changes Cloudflare)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.public_surface import catalog_markdown, remote_ingress_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = {
        ROOT / "docs/runbook/PUBLIC_ROUTE_CATALOG.md": catalog_markdown(),
        ROOT / "docs/runbook/cloudflared-ingress.example.json": json.dumps(
            remote_ingress_config("https://ticketbox.example.com", 8000), indent=2,
        ) + "\n",
    }
    for path, expected in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                print(f"stale public route artifact: {path.relative_to(ROOT)}")
                return 1
        else:
            path.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

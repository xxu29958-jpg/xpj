from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal, init_db  # noqa: E402
from app.services.identity_service import bootstrap_owner  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap v0.3 owner identity.")
    parser.add_argument("--account-name", default="我")
    parser.add_argument("--ledger-name", default="我的小票夹")
    parser.add_argument("--device-name", default="Windows 后端")
    parser.add_argument("--default-timezone", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()
    with SessionLocal() as db:
        result = bootstrap_owner(
            db,
            account_name=args.account_name,
            ledger_name=args.ledger_name,
            device_name=args.device_name,
            default_timezone=args.default_timezone,
        )

    output_dir = BACKEND_ROOT / "bootstrap"
    output_dir.mkdir(parents=True, exist_ok=True)
    owner_text = "\n".join(
        [
            "小票夹 v0.3 Owner Bootstrap",
            f"owner account: {result.account_name}",
            f"default ledger: {result.ledger_name} ({result.ledger_id})",
            f"bootstrap device: {result.device_name}",
            f"admin token: {result.admin_token}",
            f"iOS upload URL path: {result.upload_url_path}",
            f"iOS upload key: {result.upload_key}",
            f"Android pairing code: {result.pairing_code}",
            f"Pairing expires at: {result.pairing_expires_at}",
            "",
            "session/upload secrets are shown once. Store this file locally and do not commit it.",
        ]
    )
    (output_dir / "owner-bootstrap.txt").write_text(owner_text, encoding="utf-8")
    (output_dir / "owner-pairing.json").write_text(
        json.dumps(
            {
                "pairing_code": result.pairing_code,
                "ledger_name": result.ledger_name,
                "expires_at": result.pairing_expires_at,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Bootstrap files written:")
    print(output_dir / "owner-bootstrap.txt")
    print(output_dir / "owner-pairing.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

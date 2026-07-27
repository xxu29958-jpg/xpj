"""Real-backend e2e helper: lease+reset the smoke DB, seed identity, serve uvicorn.

Runs under the BACKEND venv interpreter (not the desktop .ci-venv) with
``cwd=<repo>/backend``; the parent fixture passes the runtime environment
(DATABASE_URL pointing at the dedicated smoke database, cluster identity,
pgpass file, app config placeholders, and XPJ_E2E_BACKEND_PORT). Prints one
``E2E_SEED {json}`` line once the schema is migrated and the owner identity
is seeded, then serves until terminated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)


def main() -> int:
    import uvicorn
    from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
    from scripts.test_postgres_database import dedicated_test_database_lease
    from scripts.write_test_postgres_env import render_environment

    # Prefer explicit env (CI passes real values); otherwise derive the
    # contract-local test cluster environment — the same fallback
    # tests/_infra/env.py uses, and robust against shell env mangling.
    database_url = os.environ.get("SMOKE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    cluster_identity = os.environ.get("XPJ_TEST_CLUSTER_IDENTITY")
    passfile = os.environ.get("PGPASSFILE")
    if not database_url or not cluster_identity:
        rendered = render_environment(
            host="localhost",
            port=TEST_POSTGRES_CONTRACT.ports.local,
            admin_user="postgres",
            application_user=TEST_POSTGRES_CONTRACT.application_role,
            passfile=TEST_POSTGRES_CONTRACT.default_data_dir(
                TEST_POSTGRES_CONTRACT.ports.local
            )
            / TEST_POSTGRES_CONTRACT.passfile_name,
            cluster_identity=TEST_POSTGRES_CONTRACT.local_database_identity(
                TEST_POSTGRES_CONTRACT.ports.local
            ),
        )
        database_url = database_url or rendered["SMOKE_DATABASE_URL"]
        cluster_identity = cluster_identity or rendered["XPJ_TEST_CLUSTER_IDENTITY"]
        passfile = passfile or rendered["PGPASSFILE"]
        os.environ.setdefault("PGPASSFILE", passfile)
    os.environ["DATABASE_URL"] = database_url
    os.environ["XPJ_TEST_CLUSTER_IDENTITY"] = cluster_identity
    port = int(os.environ["XPJ_E2E_BACKEND_PORT"])

    with dedicated_test_database_lease(
        database_url,
        expected_database=TEST_POSTGRES_CONTRACT.smoke_database,
        reset=True,
        cluster_identity=cluster_identity,
        passfile=passfile,
    ):
        from app.database import SessionLocal, init_db
        from app.models import Account, AuthToken, Device, Ledger, LedgerMember
        from app.services.identity_service import (
            bootstrap_owner,
            hash_secret,
            new_session_token,
        )

        init_db()
        with SessionLocal() as db:
            identity = bootstrap_owner(
                db,
                account_name="我",
                ledger_name="我的小票夹",
                device_name="e2e-owner-console",
            )
        with SessionLocal() as db:
            owner = db.query(Account).order_by(Account.id.asc()).first()
            assert owner is not None
            tester = Ledger(ledger_id="tester_1", name="另一账本", owner_account_id=owner.id)
            db.add(tester)
            db.flush()
            db.add(LedgerMember(ledger_id="tester_1", account_id=owner.id, role="owner"))
            device = Device(account_id=owner.id, device_name="e2e-owner-app", platform="android")
            db.add(device)
            db.flush()
            app_token = new_session_token()
            db.add(
                AuthToken(
                    token_hash=hash_secret(app_token),
                    account_id=owner.id,
                    device_id=device.id,
                    ledger_id="owner",
                    scope="app",
                )
            )
            db.commit()
        print(
            "E2E_SEED "
            + json.dumps(
                {
                    "pairing_code": identity.pairing_code,
                    "app_token": app_token,
                    "account_name": "我",
                    "owner_ledger_id": "owner",
                    "other_ledger_id": "tester_1",
                }
            ),
            flush=True,
        )
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=port,
            access_log=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

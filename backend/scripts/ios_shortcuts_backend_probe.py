"""Disposable cloud fixture for the system iPhone Shortcuts consumer.

This branch is not a shipping runtime or a release qualification. The fixture
uses the current application and its sealed PostgreSQL test database. Credentials
stay in the runner's private temporary directory, outside uploaded evidence.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path

from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.test_postgres_database import dedicated_test_database_lease

BASE_URL = "http://127.0.0.1:18880"


@contextmanager
def isolated_postgres(private: Path):
    from scripts.prepare_test_postgres_databases import prepare_databases
    from scripts.write_test_postgres_env import render_environment, write_passfile

    binaries = Path(subprocess.check_output(["brew", "--prefix", "postgresql@17"], text=True).strip()) / "bin"
    database = private / "postgres"
    admin_password, application_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    password_file = private / "postgres-password"
    password_file.write_text(admin_password + "\n")
    password_file.chmod(0o600)
    passfile = private / "pgpass"
    write_passfile(passfile, host="127.0.0.1", port=55432, admin_user="postgres",
        admin_password=admin_password, application_user=TEST_POSTGRES_CONTRACT.application_role,
        application_password=application_password)
    values = render_environment(host="127.0.0.1", port=55432, admin_user="postgres",
        application_user=TEST_POSTGRES_CONTRACT.application_role, passfile=passfile,
        cluster_identity=TEST_POSTGRES_CONTRACT.database_identity(str(uuid.uuid4())))
    os.environ.update(values)
    os.environ["XPJ_TEST_APPLICATION_PASSWORD"] = application_password
    with (private / "postgres-setup.log").open("w") as setup_log:
        subprocess.run([str(binaries / "initdb"), "-D", str(database), "-U", "postgres",
            "--auth=scram-sha-256", "--pwfile", str(password_file), "--encoding=UTF8", "--locale=C"],
            stdout=setup_log, stderr=subprocess.STDOUT, check=True, timeout=60)
        try:
            subprocess.run([str(binaries / "pg_ctl"), "-D", str(database), "-l", str(private / "postgres.log"),
                "-o", "-h 127.0.0.1 -p 55432 -k ''", "-w", "start"],
                stdout=setup_log, stderr=subprocess.STDOUT, check=True, timeout=60)
            prepare_databases(["smoke"], expected_major=17)
            yield values["SMOKE_DATABASE_URL"]
        finally:
            if (database / "postmaster.pid").exists():
                subprocess.run([str(binaries / "pg_ctl"), "-D", str(database), "-m", "fast", "-w", "stop"],
                    stdout=setup_log, stderr=subprocess.STDOUT, check=True, timeout=60)


def run_with_upload_backend(command: list[str], *, output: Path, log):
    if os.environ.get("GITHUB_ACTIONS") != "true" or sys.platform != "darwin":
        raise RuntimeError("This probe requires its disposable macOS cloud runner")
    os.environ["XPJ_EXTRA_LOOPBACK_HOSTS"] = "127.0.0.1:18880"
    for key in ("UPLOAD_TOKEN", "APP_TOKEN", "ADMIN_TOKEN"):
        os.environ[key] = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="ios-upload-probe-", dir=os.environ["RUNNER_TEMP"]) as temporary, \
            isolated_postgres(Path(temporary)) as database_url:
        private = Path(temporary)
        os.environ["DATABASE_URL"] = database_url
        os.environ["TICKETBOX_DATA_DIR"] = str(private / "data")
        os.environ["UPLOAD_DIR"] = str(private / "data" / "uploads")
        with dedicated_test_database_lease(database_url, expected_database=TEST_POSTGRES_CONTRACT.smoke_database,
                reset=True, cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"], passfile=os.environ["PGPASSFILE"]):
            from sqlalchemy import func, select

            from app.database import SessionLocal, init_db
            from app.models import Expense, Ledger
            from app.services.admin_service import create_upload_link
            from app.services.identity_service import bootstrap_installation_owner
            from tests._infra.currency import activate_test_currency_authority

            init_db()
            with SessionLocal() as db:
                fixture = bootstrap_installation_owner(db, operation_id="ios-shortcuts-probe",
                    installation_id="ios-shortcuts-probe", bootstrap_secret=secrets.token_urlsafe(32),
                    account_name="iOS 上传验证账户", ledger_name="iOS 上传验证账本", device_name="隔离后端")
                activate_test_currency_authority(db, "CNY")
                db.commit()
                ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == fixture.ledger_id))
                link, secret = create_upload_link(db, ledger_id=fixture.ledger_id,
                    admin_account_id=ledger.owner_account_id, default_timezone="Asia/Shanghai", auth=None)
            descriptor = os.open(private / "upload-input.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as handle:
                json.dump({"url": BASE_URL + secret.upload_url_path}, handle)
            # Deliberately keep this input out of screenshots, logs, and artifacts.
            os.environ["TICKETBOX_IOS_PRIVATE_INPUT"] = str(private / "upload-input.json")
            with (private / "server.log").open("w") as server_log:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                    "--port", "18880", "--no-access-log"], cwd=Path(__file__).resolve().parents[1],
                    stdout=server_log, stderr=subprocess.STDOUT)
                try:
                    ready = False
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline and server.poll() is None:
                        try:
                            with urllib.request.urlopen(BASE_URL + "/api/health", timeout=2) as response:
                                ready = response.status == 200
                        except (OSError, urllib.error.URLError):
                            pass
                        if ready:
                            break
                        time.sleep(0.5)
                    if not ready:
                        raise RuntimeError("The isolated real upload backend did not become ready")
                    result = {"scope": "backend-preparation-only", "source_sha": os.environ["GITHUB_SHA"],
                        "backend_reachable": True, "ledger_id": fixture.ledger_id,
                        "upload_link_public_id": link.public_id, "actual_upload_verified": False}
                    (output / "upload-backend.json").write_text(json.dumps(result, indent=2))
                    completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=600)
                    with SessionLocal() as db:
                        result["expenses_after_probe"] = db.scalar(select(func.count()).select_from(Expense))
                    (output / "upload-backend.json").write_text(json.dumps(result, indent=2))
                    return completed
                finally:
                    server.terminate()
                    server.wait(timeout=20)

"""Disposable cloud fixture for the system iPhone Shortcuts consumer.

This branch is not a shipping runtime or a release qualification. The fixture
uses the current application and its sealed PostgreSQL test database. Credentials
stay in the runner's private temporary directory, outside uploaded evidence.
"""

from __future__ import annotations

import base64
import hashlib
import io
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


def prepare_image_input(output: Path) -> tuple[str, str]:
    from PIL import Image, ImageDraw

    receipt = Image.new("RGB", (720, 960), "#faf7ef")
    drawing = ImageDraw.Draw(receipt)
    drawing.text((60, 100), "TICKETBOX / ISOLATED IOS UPLOAD\nLunch  CNY 12.34\nKeep pending for human review.",
        fill="#18231f", font_size=28, spacing=18)
    buffer = io.BytesIO()
    receipt.save(buffer, format="JPEG", quality=90)
    jpeg = buffer.getvalue()
    (output / "input-receipt.jpg").write_bytes(jpeg)
    return hashlib.sha256(jpeg).hexdigest(), base64.b64encode(jpeg).decode("ascii")


def export_redacted_text(root: Path, output: Path, upload_key: str) -> str:
    raw = root / "private-attachments"
    subprocess.run(["xcrun", "xcresulttool", "export", "attachments", "--path", str(root / "ui-control.xcresult"),
        "--output-path", str(raw)], check=True, capture_output=True)
    public = output / "attachments"
    public.mkdir()
    texts = []
    for attachment in raw.glob("*.txt"):
        text = attachment.read_text().replace(upload_key, "REDACTED_UPLOAD_KEY")
        (public / attachment.name).write_text(text)
        texts.append(text)
    # Export only explicitly captured stock Photos screens, which never display the upload URL.
    for test_case in json.loads((raw / "manifest.json").read_text()):
        for attachment in test_case["attachments"]:
            name = attachment["exportedFileName"]
            if (attachment["suggestedHumanReadableName"].startswith("Simulator Photos library for shortcut discovery_")
                    and name.endswith(".png")):
                (output / "photos-share-library.png").write_bytes((raw / name).read_bytes())
            if (attachment["suggestedHumanReadableName"].startswith("Photos available share actions_")
                    and name.endswith(".png")):
                (output / "photos-share-actions.png").write_bytes((raw / name).read_bytes())
    # Do not export automatic failure screenshots or raw xcresult bundles: they may display the URL.
    (public / "manifest.json").write_text((raw / "manifest.json").read_text().replace(upload_key, "REDACTED_UPLOAD_KEY"))
    return "\n".join(texts)


def run_with_upload_backend(command: list[str], *, output: Path, root: Path):
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
            from sqlalchemy import select

            from app.database import SessionLocal, init_db
            from app.models import Expense, Ledger
            from app.services.admin_service import create_upload_link
            from app.services.file_service import resolve_upload_path_for_tenant
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
            upload_key = secret.upload_url_path.split("/u/", 1)[1].split("?", 1)[0]
            input_digest, image_input = prepare_image_input(output)
            # xcodebuild forwards TEST_RUNNER_ variables to the test process without the prefix.
            runner_environment = dict(os.environ, TEST_RUNNER_TICKETBOX_TEST_UPLOAD_URL=BASE_URL + secret.upload_url_path,
                TEST_RUNNER_TICKETBOX_TEST_IMAGE=image_input)
            with (private / "server.log").open("w") as server_log:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                    "--port", "18880", "--no-access-log"], cwd=Path(__file__).resolve().parents[1],
                    stdout=server_log, stderr=subprocess.STDOUT)
                try:
                    ready = False
                    health_error = None
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline and server.poll() is None:
                        try:
                            with urllib.request.urlopen(BASE_URL + "/api/health", timeout=2) as response:
                                ready = response.status == 200
                        except (OSError, urllib.error.URLError) as error:
                            health_error = type(error).__name__
                        if ready:
                            break
                        time.sleep(0.5)
                    if not ready:
                        server_log.flush()
                        diagnostic = (private / "server.log").read_text()
                        credentials = [upload_key, database_url, *(os.environ[key] for key in
                            ("UPLOAD_TOKEN", "APP_TOKEN", "ADMIN_TOKEN", "XPJ_TEST_APPLICATION_PASSWORD"))]
                        for credential in credentials:
                            diagnostic = diagnostic.replace(credential, "REDACTED_CREDENTIAL")
                        diagnostic = diagnostic.replace(str(private), "ISOLATED_DATA")
                        (output / "backend-startup.log").write_text(diagnostic[-24000:])
                        (output / "backend-startup.json").write_text(json.dumps({
                            "process_exit_code": server.poll(), "last_health_error": health_error,
                            "backend_reachable": False}, indent=2))
                        raise RuntimeError("The isolated real upload backend did not become ready")
                    result = {"scope": "isolated-system-file-upload", "source_sha": os.environ["GITHUB_SHA"],
                        "backend_reachable": True, "ledger_id": fixture.ledger_id,
                        "upload_link_public_id": link.public_id, "actual_upload_verified": False,
                        "input_sha256": input_digest, "share_sheet_and_receipt_branches_verified": False}
                    (output / "upload-backend.json").write_text(json.dumps(result, indent=2))
                    raw_log = private / "ui-control.log"
                    try:
                        with raw_log.open("w") as log:
                            completed = subprocess.run(command, env=runner_environment,
                                stdout=log, stderr=subprocess.STDOUT, timeout=600)
                    finally:
                        (output / "ui-control.log").write_text(raw_log.read_text().replace(upload_key, "REDACTED_UPLOAD_KEY"))
                    observed = export_redacted_text(root, output, upload_key)
                    if completed.returncode:
                        device_id = json.loads((output / "environment.json").read_text())["device_id"]
                        share_logs = subprocess.run([
                            "xcrun", "simctl", "spawn", device_id, "log", "show", "--last", "5m",
                            "--style", "compact", "--info", "--predicate",
                            'process == "Shortcuts" OR process == "MobileSlideShow" OR '
                            'eventMessage CONTAINS "Run-Workflow"',
                        ], capture_output=True, text=True, timeout=45)
                        diagnostic = (share_logs.stdout + share_logs.stderr).replace(upload_key, "REDACTED_UPLOAD_KEY")
                        (output / "photos-share-services.log").write_text(diagnostic[-240000:])
                        (output / "photos-share-services.json").write_text(json.dumps({
                            "exit_code": share_logs.returncode, "scope": "last-five-minutes-system-share-services",
                        }, indent=2))
                    with SessionLocal() as db:
                        rows = db.scalars(select(Expense)).all()
                        result["expenses_after_probe"] = len(rows)
                        result["uploads"] = []
                        for expense in rows:
                            original = resolve_upload_path_for_tenant(expense.image_path, expense.tenant_id)
                            original_digest = hashlib.sha256(original.read_bytes()).hexdigest() if original and original.is_file() else None
                            result["uploads"].append({"public_id": expense.public_id, "ledger_id": expense.tenant_id,
                                "status": expense.status, "image_hash": expense.image_hash, "original_sha256": original_digest,
                                "receipt_visible": expense.public_id in observed})
                    result["photos_share_entry_verified"] = completed.returncode == 0
                    result["actual_upload_verified"] = len(rows) == 1 and all(
                        row["ledger_id"] == fixture.ledger_id and row["status"] == "pending" and row["receipt_visible"]
                        and row["image_hash"] == row["original_sha256"] and row["original_sha256"] is not None
                        for row in result["uploads"])
                    (output / "upload-backend.json").write_text(json.dumps(result, indent=2))
                    if completed.returncode == 0 and not result["actual_upload_verified"]:
                        raise AssertionError("The system upload did not preserve one pending original and its visible receipt")
                    return completed
                finally:
                    server.terminate()
                    server.wait(timeout=20)

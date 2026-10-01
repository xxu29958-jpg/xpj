"""Narrow cold-copy qualification on a disposable GitHub-hosted Windows machine.

The installed EXE creates/verifies the archive. Only a separate PG copy is opened
to prove material readability; no installation restore or identity publication.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "distribution/windows/lifecycle"))


def run(argv: list[str], *, timeout: int = 300, expected: int = 0) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    if completed.returncode != expected:
        raise AssertionError(f"{Path(argv[0]).name} returned {completed.returncode}, expected {expected}; {completed.stderr[-1500:]}")
    return completed.stdout if expected == 0 else completed.stderr


def services(action: str) -> None:
    names = ("TicketboxBackend", "TicketboxPg") if action == "Stop" else ("TicketboxPg", "TicketboxBackend")
    state = "Stopped" if action == "Stop" else "Running"
    for name in names:
        run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"$ErrorActionPreference='Stop'; {action}-Service -Name '{name}'; (Get-Service '{name}').WaitForStatus('{state}',[TimeSpan]::FromSeconds(60))"])


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def seed(password: str, data: Path) -> tuple[str, str]:
    from app.models import Account, Expense, Ledger
    from tests._infra.currency import activate_test_currency_authority

    relative = "cold-copy-drill/2026/10/receipt.png"
    original = data / "attachments/originals" / relative
    original.parent.mkdir(parents=True)
    # An actual PNG fixture; financial semantics are unchanged by the copy.
    from PIL import Image

    Image.new("RGB", (64, 64), (163, 150, 125)).save(original)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres", password=password,
                                      host="127.0.0.1", port=5432, database="ticketbox"))
    try:
        with Session(engine) as db:
            activate_test_currency_authority(db, "CNY")
            account = Account(display_name="Cold copy fixture")
            db.add(account)
            db.flush()
            ledger = Ledger(ledger_id="cold-copy-drill", name="Cold copy fixture", owner_account_id=account.id)
            db.add(ledger)
            db.flush()
            db.add(Expense(tenant_id=ledger.ledger_id, amount_cents=1234, original_amount_minor=1234,
                           home_currency_code="CNY", original_currency_code="CNY", image_path=relative,
                           image_hash=digest, source="manual", status="pending"))
            db.commit()
    finally:
        engine.dispose()
    return relative, digest


def facts(password: str, port: int) -> dict:
    with psycopg.connect(host="127.0.0.1", port=port, user="postgres", password=password,
                        dbname="ticketbox", row_factory=dict_row, connect_timeout=10) as db:
        return {
            "draft": db.execute("SELECT public_id, amount_cents, original_amount_minor, image_hash, row_version, status FROM expenses WHERE tenant_id='cold-copy-drill'").fetchall(),
            "authority": db.execute("SELECT dataset_id, client_generation, restore_epoch, schema_revision FROM dataset_authority").fetchall(),
            "currency": db.execute("SELECT state, home_currency_code, minor_unit_exponent, rounding_mode, binding_revision FROM installation_currency_bindings").fetchall(),
            "schema": db.execute("SELECT version_num FROM alembic_version").fetchall(),
            "roles": db.execute("SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname LIKE 'ticketbox_%' ORDER BY rolname").fetchall(),
            "cluster": db.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone(),
        }


def copied_cluster(archive_path: Path, evidence: Path, pg_bin: Path, password: str) -> dict:
    extracted = evidence / "readability-copy"
    copied_data = extracted / "data/pgdata"
    with zipfile.ZipFile(archive_path) as archive:
        for name in archive.namelist():
            if name.startswith("data/pgdata/"):
                archive.extract(name, extracted)
    assert copied_data.resolve().is_relative_to(evidence.resolve())
    port = free_port()
    pg_ctl = str(pg_bin / "pg_ctl.exe")
    started = False
    try:
        run([pg_ctl, "start", "-D", str(copied_data), "-l", str(evidence / "copy-pg.log"),
             "-o", f"-p {port} -h 127.0.0.1", "-w", "-t", "60"], timeout=90)
        started = True
        return facts(password, port)
    finally:
        if started or (copied_data / "postmaster.pid").exists():
            run([pg_ctl, "stop", "-D", str(copied_data), "-m", "fast", "-w", "-t", "60"], timeout=90)


def interrupt_real_copy(lifecycle: Path, evidence: Path) -> None:
    partial = evidence / "interrupted.tbxcold"
    child = subprocess.Popen([str(lifecycle), "cold-copy", "--output", str(partial)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 180
    try:
        while child.poll() is None and time.monotonic() < deadline:
            if partial.exists() and partial.stat().st_size > 1024 * 1024:
                child.kill()
                child.wait(timeout=15)
                rejected = json.loads(run([str(lifecycle), "verify-cold-copy", "--source", str(partial)], expected=2))
                assert rejected["ok"] is False
                return
            time.sleep(0.02)
        raise AssertionError("did not observe an in-progress cold-copy process")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)


def qualify(installer: Path, evidence: Path) -> dict:
    from ticketbox_lifecycle.runtime.windows_known_folders import ticketbox_install_root, ticketbox_program_data_root

    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("This drill is restricted to a disposable GitHub-hosted Windows runner.")
    if os.name != "nt" or not ctypes.windll.shell32.IsUserAnAdmin():
        raise SystemExit("An elevated disposable Windows runner is required.")
    app, program_data = ticketbox_install_root(), ticketbox_program_data_root()
    assert not app.exists() and not program_data.exists(), "The runner is not a fresh isolated Ticketbox host"
    for name in ("TicketboxPg", "TicketboxBackend"):
        run(["sc.exe", "query", name], expected=1060)
    for port in (5432, 8000):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    evidence.mkdir(parents=True, exist_ok=False)
    setup_sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], timeout=600)
    lifecycle = app / "bin/lifecycle/TicketboxLifecycle.exe"
    machine = program_data / "machine"
    binding_bytes = (machine / "installation.json").read_bytes()
    binding = json.loads(binding_bytes)
    data = Path(binding["data_root"])
    password = (machine / "secrets/postgres.password").read_text().strip()
    relative, original_sha = seed(password, data)
    before = facts(password, 5432)
    live_target = evidence / "running-rejected.tbxcold"
    refused = json.loads(run([str(lifecycle), "cold-copy", "--output", str(live_target)], expected=2))
    assert refused["code"] == "cold_services_running"
    assert not live_target.exists(), "live services must be rejected before creating the archive"
    services("Stop")
    try:
        pg_control = data / "pgdata/global/pg_control"
        control_before = pg_control.read_bytes()
        interrupt_real_copy(lifecycle, evidence)
        archive = evidence / "qualified.tbxcold"
        result = json.loads(run([str(lifecycle), "cold-copy", "--output", str(archive)]))
        verified = json.loads(run([str(lifecycle), "verify-cold-copy", "--source", str(archive)]))
        assert result["ok"] and verified["ok"] and result["identity"] == verified["identity"]
        archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        refused = json.loads(run([str(lifecycle), "cold-copy", "--output", str(archive)], expected=2))
        assert refused["code"] == "cold_output_exists"
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_sha
        assert pg_control.read_bytes() == control_before
        assert (machine / "installation.json").read_bytes() == binding_bytes
        with zipfile.ZipFile(archive) as opened:
            assert opened.read("machine/installation.json") == binding_bytes
            assert hashlib.sha256(opened.read(f"data/attachments/originals/{relative}")).hexdigest() == original_sha
        copied = copied_cluster(archive, evidence, app / "postgresql/bin", password)
        assert copied == before, "copied PostgreSQL lost original identity, schema, roles or draft facts"
        assert copied["cluster"]["system_identifier"] == result["identity"]["postgres_system_identifier"]
        assert (data / "attachments/originals" / relative).is_file()
        assert pg_control.read_bytes() == control_before, "opening the separate copy changed the original cluster"
    finally:
        services("Start")
    assert facts(password, 5432) == before, "source facts changed after reopening the original services"
    return {"checkout_sha": run(["git", "rev-parse", "HEAD"]).strip(), "setup_sha256": setup_sha,
            "lifecycle_sha256": hashlib.sha256(lifecycle.read_bytes()).hexdigest(),
            "cold_archive_sha256": archive_sha, "files": result["files"], "bytes": result["bytes"],
            "original_sha256": original_sha, "facts": copied,
            "verified_leg": "Installed frozen CLI; live refusal, clean stop, killed partial copy rejected, new private archive, complete readback, overwrite refusal, separate PG readability, original source reopening"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    outcome = qualify(arguments.installer.resolve(), arguments.evidence.resolve())
    (arguments.evidence / "business-result.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "checkout_sha": outcome["checkout_sha"], "setup_sha256": outcome["setup_sha256"]}))

"""Subprocess isolation probe scripts for ticketbox-database-maintenance.exe."""

from __future__ import annotations

_ISOLATION_GUARD_PREAMBLE = r"""
import os
import sys
from pathlib import Path

mode = sys.argv[2]

FORBIDDEN_MODULES = {
    "app.config",
    "dotenv",
    "app.database._core",
    "app.services.file_service",
    "app.services.runtime_settings_store",
    "app.services.attachment_cleanup_service",
    "app.services.currency_binding_service",
}
FORBIDDEN_EVENTS: list[str] = []


class _ForbiddenImportBlocker:
    def find_spec(self, fullname, path, target=None):
        if fullname in FORBIDDEN_MODULES:
            msg = f"mode {mode} attempted forbidden import: {fullname}"
            FORBIDDEN_EVENTS.append(msg)
            raise AssertionError(msg)
        if fullname == "app.database":
            msg = f"mode {mode} attempted to import real app.database.__init__"
            FORBIDDEN_EVENTS.append(msg)
            raise AssertionError(msg)
        return None


def _forbidden_open_audit(event, args):
    if event != "open" or not args:
        return
    target = args[0]
    if isinstance(target, (str, bytes, os.PathLike)):
        name = Path(os.fsdecode(target)).name.casefold()
        if name in {".env", "runtime-settings.json"}:
            msg = f"mode {mode} attempted forbidden file open: {target!r}"
            FORBIDDEN_EVENTS.append(msg)
            raise AssertionError(msg)


sys.meta_path.insert(0, _ForbiddenImportBlocker())
sys.addaudithook(_forbidden_open_audit)


def assert_isolated() -> None:
    assert not FORBIDDEN_EVENTS, f"maintenance mode {mode} recorded forbidden events: {FORBIDDEN_EVENTS}"
    loaded = [name for name in FORBIDDEN_MODULES if name in sys.modules]
    assert not loaded, f"maintenance mode {mode} loaded forbidden runtime modules: {loaded}"
    assert "app.database" not in sys.modules, f"maintenance mode {mode} left app.database loaded"
    assert "SENTINEL_DOTENV_LOADED" not in os.environ, "maintenance mode loaded ambient .env"
"""


_MAINTENANCE_ISOLATION_PROBE = _ISOLATION_GUARD_PREAMBLE + r"""
import contextlib
import hashlib
import importlib.util
import io
import json
import zipfile
from uuid import uuid4

backend_root = Path(sys.argv[1])
launch_path = backend_root / "packaging" / "launch.py"
explicit_data_root = Path(sys.argv[3])
pgpass_path = Path(sys.argv[4])
backup_path = Path(sys.argv[5])
program_file = Path(sys.argv[6])
sys.path.insert(0, str(backend_root))

spec = importlib.util.spec_from_file_location("ticketbox_isolation_launch", launch_path)
assert spec is not None and spec.loader is not None
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
assert_isolated()

@contextlib.contextmanager
def _noop_secret(_path):
    yield _path

import sqlalchemy
from sqlalchemy import create_engine as _real_create_engine, event
from sqlalchemy.orm import Session
from app.services import secure_file

secure_file.hold_installer_machine_secret_for_read = _noop_secret
secure_file.hold_protected_file_for_read = _noop_secret

def _make_seeded_sqlite_engine(*, with_owner_and_original: bool, upload_root: Path):
    from sqlalchemy import CheckConstraint, JSON
    from sqlalchemy.dialects.postgresql import JSONB
    from app.database_model_registry import Base
    import app.models as m
    from app.services.identity_service import bootstrap_installation_owner

    db_file = explicit_data_root.parent / "probe.sqlite3"
    eng = _real_create_engine(f"sqlite:///{db_file.as_posix()}", future=True)

    @event.listens_for(eng, "connect")
    def _register_pg_shims(dbapi_connection, _connection_record):
        dbapi_connection.create_function("pg_advisory_xact_lock", -1, lambda *_args: None)

    @event.listens_for(eng, "before_cursor_execute", retval=True)
    def _rewrite_pg_session_sql(conn, cursor, statement, parameters, context, executemany):
        upper = statement.strip().upper()
        if upper.startswith(("SET ROLE", "RESET ROLE", "SET TRANSACTION READ ONLY", "SET LOCAL ")):
            return "SELECT 1", ()
        return statement, parameters

    for table in Base.metadata.tables.values():
        table.constraints = {c for c in table.constraints if not isinstance(c, CheckConstraint)}
        table.indexes = {idx for idx in table.indexes if "postgresql_where" not in idx.dialect_options.get("postgresql", {})}
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
    Base.metadata.create_all(eng)
    source_install = "11111111-1111-4111-8111-111111111111"
    dataset_id = "22222222-2222-4222-8222-222222222222"
    old_secret = "a" * 64
    if with_owner_and_original:
        with Session(eng, expire_on_commit=False) as db:
            claim = bootstrap_installation_owner(
                db,
                operation_id="fresh-op-1",
                installation_id=source_install,
                bootstrap_secret=old_secret,
                account_name="Owner",
                ledger_name="Mine",
                device_name="Win",
                commit=False,
            )
            db.add(
                m.DatasetAuthorityRecord(
                    singleton_id=1,
                    dataset_id=dataset_id,
                    client_generation=source_install,
                    restore_epoch=0,
                    schema_revision="20261101_0001",
                    schema_min_compatible="1.3.0",
                    semantic_revision="ticketbox-dataset-semantics-v1",
                )
            )
            img_bytes = b"\x89PNG\r\n\x1a\nexplicit-maintenance-original"
            img_sha = hashlib.sha256(img_bytes).hexdigest()
            img_path = upload_root / claim.ledger_id / "receipt.png"
            img_path.parent.mkdir(parents=True, exist_ok=True)
            img_path.write_bytes(img_bytes)
            db.add(
                m.Expense(
                    tenant_id=claim.ledger_id,
                    amount_cents=1200,
                    original_amount_minor=1200,
                    category="food",
                    image_path=f"uploads/{claim.ledger_id}/receipt.png",
                    image_hash=img_sha,
                )
            )
            db.commit()
    return eng, source_install, dataset_id, old_secret

DB_URL = "postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256"

if mode == "--validate-generation-program":
    program_digest = hashlib.sha256(program_file.read_bytes()).hexdigest()
    launch._resolve_generation_program = lambda _p: program_file
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    rc = launch._dispatch_maintenance_mode(
        [
            "--validate-generation-program",
            "--generation-program-path",
            "DATABASE_GENERATION_PROGRAM.json",
            "--expected-generation-program-sha256",
            program_digest,
        ]
    )
    assert rc == 0
elif mode == "--fresh-schema-upgrade":
    sqlite_engine, source_install, dataset_id, _secret = _make_seeded_sqlite_engine(
        with_owner_and_original=False,
        upload_root=explicit_data_root / "app" / "uploads",
    )
    target_rev = json.loads(program_file.read_text(encoding="utf-8"))["target_revision"]
    mod = launch._load_fresh_schema_upgrade_module()
    alembic_upgraded: list[str] = []
    mod.create_engine = lambda *_a, **_kw: sqlite_engine
    mod._prearmed_transaction = lambda conn, **_kw: conn.begin()
    mod.assume_managed_postgres_schema_owner = lambda *_a, **_kw: None
    mod.seal_runtime_authority_tables = lambda *_a, **_kw: True
    mod.seal_upgrade_attestation_guard = lambda *_a, **_kw: True
    mod._current_revision = lambda _conn: target_rev if alembic_upgraded else None

    def _fake_alembic_upgrade(cfg, rev):
        assert cfg.attributes.get("connection") is not None
        alembic_upgraded.append(rev)

    mod.command.upgrade = _fake_alembic_upgrade
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--fresh-schema-upgrade",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--target-revision",
                target_rev,
                "--dataset-id",
                dataset_id,
                "--client-generation",
                source_install,
                "--schema-min-compatible",
                "1.3.0",
                "--semantic-revision",
                "ticketbox-dataset-semantics-v1",
                "--operation-id",
                "fresh-op-1",
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-fresh-schema-upgrade-result-v1"
    assert payload["result"] == "upgraded"
    assert alembic_upgraded == [target_rev]
    with sqlite_engine.connect() as conn:
        bound_row = conn.execute(
            sqlalchemy.text("SELECT dataset_id, client_generation, schema_revision FROM dataset_authority WHERE singleton_id = 1")
        ).mappings().one()
        assert bound_row["dataset_id"] == dataset_id
        assert bound_row["client_generation"] == source_install
        assert bound_row["schema_revision"] == target_rev
elif mode == "--database-generation-verify-target":
    sqlite_engine, _src, _ds, _secret = _make_seeded_sqlite_engine(
        with_owner_and_original=False,
        upload_root=explicit_data_root / "app" / "uploads",
    )
    program_digest = hashlib.sha256(program_file.read_bytes()).hexdigest()
    target_rev = json.loads(program_file.read_text(encoding="utf-8"))["target_revision"]
    launch._resolve_generation_program = lambda _p: program_file
    mod = launch._load_database_generation_target_module()
    mod._create_engine = lambda *_a, **_kw: sqlite_engine
    mod._prearmed_transaction = lambda conn, **_kw: conn.begin()
    mod.assume_managed_postgres_schema_owner = lambda *_a, **_kw: None
    mod.assert_release_head = lambda _conn, expected_revision: expected_revision
    mod.read_money_schema_shape = lambda _conn: {"shape_sha256": "b" * 64}
    mod.canonical_money_facts_sha256 = lambda _conn, **_kw: "c" * 64
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--database-generation-verify-target",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--generation-program-path",
                "DATABASE_GENERATION_PROGRAM.json",
                "--expected-generation-program-sha256",
                program_digest,
                "--operation-id",
                "11111111-1111-4111-8111-111111111111",
                "--database",
                "ticketbox",
                "--target-revision",
                target_rev,
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-database-generation-target-verification-v2"
    assert payload["alembic_revision"] == target_rev
    assert payload["resource_shape_sha256"] == "b" * 64
    assert payload["money_facts_sha256"] == "c" * 64
elif mode == "--upgrade-existing-dataset":
    import sqlite3

    source_install = "11111111-1111-4111-8111-111111111111"
    dataset_id = "22222222-2222-4222-8222-222222222222"
    upgrade_op_id = "55555555-5555-4555-8555-555555555555"
    source_rev = "20261029_0002"
    target_rev = json.loads(program_file.read_text(encoding="utf-8"))["target_revision"]

    upload_root = explicit_data_root / "app" / "uploads"
    owner_dir = upload_root / "owner"
    owner_dir.mkdir(parents=True, exist_ok=True)
    app_dir = explicit_data_root.parent / "app_program"
    pg_bin = app_dir / "postgresql" / "bin" / "postgres.exe"
    pg_bin.parent.mkdir(parents=True, exist_ok=True)
    pg_bin_bytes = b"pg-bin-payload"
    pg_bin.write_bytes(pg_bin_bytes)

    files_to_write = {
        "demo.png": b"\x89PNG\r\n\x1a\nexplicit-upgrade-img",
        "thumb.jpg": b"\xff\xd8\xffthumb-bytes",
        "pending.png": b"\x89PNG\r\n\x1a\npending-cleanup-img",
        "debt.png": b"\x89PNG\r\n\x1a\ndebt-bill-img",
        "debt_pending.png": b"\x89PNG\r\n\x1a\ndebt-pending-img",
    }
    shas: dict[str, str] = {}
    for fname, raw in files_to_write.items():
        (owner_dir / fname).write_bytes(raw)
        shas[fname] = hashlib.sha256(raw).hexdigest()

    rel_manifest_bytes = json.dumps({
        "release_id": "1.2.1",
        "max_schema_revision": source_rev,
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
        "immutable_payload": {
            "files": [
                {
                    "path": "postgresql/bin/postgres.exe",
                    "size": len(pg_bin_bytes),
                    "sha256": hashlib.sha256(pg_bin_bytes).hexdigest(),
                }
            ]
        },
    }).encode("utf-8")
    rel_manifest_sha = hashlib.sha256(rel_manifest_bytes).hexdigest()

    archive_files: dict[str, bytes] = {
        "data/pgdata/PG_VERSION": b"16\n",
        "data/pgdata/global/pg_control": b"pg-control-bytes",
        "data/app/.env": b"DATABASE_URL=postgresql://stub\n",
        "machine/installation.json": json.dumps({
            "schema": "ticketbox-installed-instance-v1",
            "install_id": source_install,
            "dataset_id": dataset_id,
            "expected_restore_epoch": 0,
            "active_release_id": "1.2.1",
            "release_manifest_sha256": rel_manifest_sha,
        }).encode("utf-8"),
        "machine/secrets/postgres.password": b"pw1\n",
        "machine/secrets/ticketbox_migrator.password": b"pw2\n",
        "machine/secrets/ticketbox_runtime.password": b"pw3\n",
        "machine/secrets/pgpass": b"127.0.0.1:5432:ticketbox:ticketbox_migrator:pw2\n",
        "machine/operations/history/op-install.json": json.dumps({
            "schema": "ticketbox-lifecycle-operation-v2",
            "phase": "committed",
            "kind": "install",
            "operation_id": "66666666-6666-4666-8666-666666666666",
            "install_id": source_install,
            "dataset_id": dataset_id,
            "release_manifest_sha256": rel_manifest_sha,
        }).encode("utf-8"),
        "program/releases/1.2.1/release-manifest.json": rel_manifest_bytes,
        "program/postgresql/bin/postgres.exe": pg_bin_bytes,
    }
    for fname, raw in files_to_write.items():
        archive_files[f"data/app/uploads/owner/{fname}"] = raw

    entries: dict[str, object] = {
        "program/": None,
        "machine/": None,
        "data/pgdata/": None,
        "data/attachments/": None,
        "data/app/": None,
    }
    for rel, raw in archive_files.items():
        entries[rel] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    cold_copy_manifest = {
        "schema": "ticketbox-beta-cold-copy-v2",
        "complete": True,
        "public_connectivity": {
            "excluded_directory": "machine/connectors/cloudflare/secrets",
            "credentials": "not_backed_up",
            "after_restore": "configure_again",
        },
        "identity": {
            "install_id": source_install,
            "dataset_id": dataset_id,
            "restore_epoch": 0,
            "schema_revision": source_rev,
            "release_id": "1.2.1",
            "release_manifest_sha256": rel_manifest_sha,
            "postgres_major": 16,
        },
        "entries": entries,
    }
    with zipfile.ZipFile(backup_path, "w") as zf:
        zf.writestr("COLD_COPY.json", json.dumps(cold_copy_manifest).encode("utf-8"))
        for dir_name in ("program/", "machine/", "data/pgdata/", "data/attachments/", "data/app/"):
            zf.writestr(dir_name, b"")
        for rel, raw in archive_files.items():
            zf.writestr(rel, raw)
    backup_sha = hashlib.sha256(backup_path.read_bytes()).hexdigest()

    # SQLite DB with attached `public` schema and JSONB converter matching psycopg dict return!
    sqlite3.register_converter("JSONB", lambda raw: json.loads(raw.decode("utf-8")))
    main_db = explicit_data_root.parent / "upgrade_main.sqlite3"
    public_db = explicit_data_root.parent / "upgrade_public.sqlite3"
    upgrade_engine = _real_create_engine(
        f"sqlite:///{main_db.as_posix()}",
        connect_args={"detect_types": sqlite3.PARSE_DECLTYPES},
        future=True,
    )

    @event.listens_for(upgrade_engine, "connect")
    def _attach_public(dbapi_connection, _connection_record):
        dbapi_connection.execute(f"ATTACH DATABASE '{public_db.as_posix()}' AS public")

    expense_cleanup_json = json.dumps({
        "request_id": str(uuid4()),
        "reason": "after_confirm",
        "requested_at": "2026-11-26T00:00:00Z",
        "image": {
            "reference": "uploads/owner/pending.png",
            "outcome": "pending",
            "completed_at": None,
            "error_code": None,
        },
        "thumbnail": None,
    })
    debt_cleanup_json = json.dumps({
        "request_id": str(uuid4()),
        "reason": "after_confirm",
        "requested_at": "2026-11-26T00:00:00Z",
        "image": {
            "reference": "uploads/owner/debt_pending.png",
            "outcome": "pending",
            "completed_at": None,
            "error_code": None,
        },
        "thumbnail": None,
    })
    with upgrade_engine.begin() as conn:
        conn.execute(sqlalchemy.text(
            "CREATE TABLE public.expenses ("
            "tenant_id TEXT, image_path TEXT, image_hash TEXT, image_deleted_at TEXT, "
            "thumbnail_path TEXT, thumbnail_deleted_at TEXT, attachment_cleanup_request JSONB)"
        ))
        conn.execute(sqlalchemy.text(
            "INSERT INTO public.expenses VALUES ("
            "'owner', 'uploads/owner/demo.png', :img_sha, NULL, "
            "'uploads/owner/thumb.jpg', NULL, :cleanup_json)"
        ), {"img_sha": shas["demo.png"], "cleanup_json": expense_cleanup_json})
        conn.execute(sqlalchemy.text(
            "CREATE TABLE public.debt_bill_captures ("
            "tenant_id TEXT, image_path TEXT, image_hash TEXT, image_deleted_at TEXT, "
            "attachment_cleanup_request JSONB)"
        ))
        conn.execute(sqlalchemy.text(
            "INSERT INTO public.debt_bill_captures VALUES ("
            "'owner', 'uploads/owner/debt.png', :debt_sha, NULL, :debt_cleanup)"
        ), {"debt_sha": shas["debt.png"], "debt_cleanup": debt_cleanup_json})

    mod = launch._load_existing_dataset_upgrade_module()
    verified_paths: list[str] = []
    orig_verify_file = mod._VerifiedBackupArchive.verify_file

    def _spied_verify_file(self, path, *, data_root, expected_sha256=None):
        verified_paths.append(Path(path).name)
        return orig_verify_file(self, path, data_root=data_root, expected_sha256=expected_sha256)

    mod._VerifiedBackupArchive.verify_file = _spied_verify_file

    def _sqlite_migration_run(self, **kwargs):
        pre = kwargs.get("pre_migration_check")
        assert callable(pre)
        with upgrade_engine.connect() as conn:
            pre(conn)
        return "upgraded"

    mod.ManagedPostgresMigrationRuntimeV1.run = _sqlite_migration_run
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--upgrade-existing-dataset",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--source-revision",
                source_rev,
                "--target-revision",
                target_rev,
                "--dataset-id",
                dataset_id,
                "--installation-id",
                source_install,
                "--expected-restore-epoch",
                "0",
                "--operation-id",
                upgrade_op_id,
                "--data-root",
                str(explicit_data_root),
                "--backup-archive",
                str(backup_path),
                "--backup-archive-sha256",
                backup_sha,
                "--app-dir",
                str(app_dir),
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-existing-dataset-upgrade-result-v1"
    assert payload["result"] == "upgraded"
    assert set(verified_paths) == {"demo.png", "thumb.jpg", "pending.png", "debt.png", "debt_pending.png"}, verified_paths
elif mode == "--fresh-owner-claim":
    sqlite_engine, source_install, _ds, secret = _make_seeded_sqlite_engine(
        with_owner_and_original=False,
        upload_root=explicit_data_root / "app" / "uploads",
    )
    sqlalchemy.create_engine = lambda *_a, **_kw: sqlite_engine
    # Run BOTH create and idempotent replay through the real dispatcher!
    for _pass in range(2):
        sys.stdin = io.TextIOWrapper(io.BytesIO((secret + "\n").encode("ascii")))
        rc = launch._dispatch_maintenance_mode(
            [
                "--fresh-owner-claim",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--operation-id",
                "fresh-op-1",
                "--installation-id",
                source_install,
            ]
        )
        assert rc == 0
elif mode == "--verify-preserved-dataset":
    upload_root = explicit_data_root / "app" / "uploads"
    sqlite_engine, source_install, dataset_id, _secret = _make_seeded_sqlite_engine(
        with_owner_and_original=True,
        upload_root=upload_root,
    )
    sqlalchemy.create_engine = lambda *_a, **_kw: sqlite_engine
    from app import cold_restore_runtime, database_maintenance_runtime as dmr
    real_ctx = dmr.standalone_database_package
    @contextlib.contextmanager
    def _instrumented_pkg():
        with real_ctx():
            from app.database import _managed_postgres_role_authority as role_mod
            from app.database import _release_schema_readiness as ready_mod
            role_mod.assume_managed_postgres_schema_owner = lambda *_a, **_kw: None
            ready_mod.assert_release_head = lambda *_a, **_kw: None
            yield
    cold_restore_runtime.standalone_database_package = _instrumented_pkg
    sys.stdin = io.TextIOWrapper(io.BytesIO(b""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--verify-preserved-dataset",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--data-root",
                str(explicit_data_root),
                "--dataset-id",
                dataset_id,
                "--installation-id",
                source_install,
                "--expected-restore-epoch",
                "0",
                "--schema-revision",
                "20261101_0001",
                "--semantic-revision",
                "ticketbox-dataset-semantics-v1",
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-preserved-dataset-verify-v1"
    assert payload["verified_originals"] == 1
elif mode == "--restore-cold-dataset":
    upload_root = explicit_data_root / "app" / "uploads"
    sqlite_engine, source_install, dataset_id, old_secret = _make_seeded_sqlite_engine(
        with_owner_and_original=True,
        upload_root=upload_root,
    )
    sqlalchemy.create_engine = lambda *_a, **_kw: sqlite_engine
    from app import cold_restore_runtime, database_maintenance_runtime as dmr
    real_ctx = dmr.standalone_database_package
    @contextlib.contextmanager
    def _instrumented_pkg():
        with real_ctx():
            from app.database import _managed_postgres_role_authority as role_mod
            from app.database import _release_schema_readiness as ready_mod
            from app.database import _runtime_authority_privileges as priv_mod
            role_mod.assume_managed_postgres_schema_owner = lambda *_a, **_kw: None
            ready_mod.assert_release_head = lambda *_a, **_kw: None
            priv_mod.seal_upgrade_attestation_guard = lambda *_a, **_kw: True
            yield
    cold_restore_runtime.standalone_database_package = _instrumented_pkg
    body = json.dumps({
        "source": {
            "install_id": source_install,
            "dataset_id": dataset_id,
            "restore_epoch": 0,
            "schema_revision": "20261101_0001",
        },
        "installation_id": "33333333-3333-4333-8333-333333333333",
        "backup_id": "44444444-4444-4444-8444-444444444444",
        "operation_id": "restore-op-1",
        "bootstrap_secret": "b" * 64,
        "recovery_secret": old_secret,
    }).encode("utf-8")
    sys.stdin = io.TextIOWrapper(io.BytesIO(body))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = launch._dispatch_maintenance_mode(
            [
                "--restore-cold-dataset",
                "--database-url",
                DB_URL,
                "--pgpassfile",
                str(pgpass_path),
                "--data-root",
                str(explicit_data_root),
            ]
        )
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["schema"] == "ticketbox-cold-restore-dataset-v1"
    assert payload["verified_originals"] == 1
    assert payload["restore_epoch"] == 1
else:
    raise AssertionError(f"unknown mode {mode}")

assert_isolated()
"""


_FROZEN_SEAM_PROBE = r"""
import sys
from pathlib import Path

backend_root = Path(sys.argv[1])
fake_meipass = Path(sys.argv[2])
sys.path.insert(0, str(backend_root))

# Simulate PyInstaller frozen layout: ONLY physical action files exist on disk under
# _MEIPASS/app/database/, while __init__.py does NOT exist on disk (lives in PYZ).
sys.frozen = True
sys._MEIPASS = str(fake_meipass)

from app.database_maintenance_runtime import standalone_database_package

assert not (fake_meipass / "app" / "database" / "__init__.py").exists()
with standalone_database_package():
    assert "app.database" in sys.modules
    assert sys.modules["app.database"].__path__ == [str((fake_meipass / "app" / "database").resolve())]
assert "app.database" not in sys.modules
"""


_BARE_OPEN_AUDIT_PROBE = _ISOLATION_GUARD_PREAMBLE + r"""
target_name = sys.argv[1]
caught_direct = False
try:
    open(target_name, encoding="utf-8")
except AssertionError as exc:
    assert "attempted forbidden file open" in str(exc)
    caught_direct = True
assert caught_direct, f"shared isolation guard failed to block bare relative open: {target_name}"

# Even when the open() AssertionError is swallowed, assert_isolated() MUST still fail on FORBIDDEN_EVENTS.
try:
    assert_isolated()
except AssertionError as exc:
    assert "recorded forbidden events" in str(exc)
else:
    raise SystemExit("assert_isolated() failed to catch swallowed forbidden open event")
"""



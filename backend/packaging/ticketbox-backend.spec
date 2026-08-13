# PyInstaller spec — frozen Ticketbox backend (no OCR; OCR is opt-in and heavy).
#
# Build from the backend/ directory:
#     .venv-build\Scripts\pyinstaller.exe packaging\ticketbox-backend.spec
# (scripts/build_backend_exe.ps1 wraps this with a clean build venv.)
#
# Output (ADR-0047 §8): onedir + windowed (console=False). The build produces a
# FOLDER dist\ticketbox-backend\ (ticketbox-backend.exe + _internal\), not a
# single self-extracting file. onedir starts faster (no per-launch temp
# extraction), keeps psycopg's native DLLs on disk, and is the form the Shawl
# service wrapper + Inno installer expect.
#
# All paths are absolute (derived from SPECPATH = this file's dir) so the build
# is cwd-independent. Layout note: app/config.py and app/database resolve paths
# via Path(__file__).parents[N], which at runtime points at the bundle root
# (sys._MEIPASS — the _internal\ dir in onedir). So alembic.ini and migrations/
# are bundled at the bundle ROOT (dest "." / "migrations") to match backend_root;
# static/templates stay under app/ to match Path(app/...).parent.

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

HERE = SPECPATH  # injected by PyInstaller: directory of this spec (backend/packaging)
BACKEND = os.path.dirname(HERE)

# Spec-file Python executes before Analysis applies pathex. Make the copied
# backend source importable before asking PyInstaller to enumerate app.*;
# otherwise collect_submodules silently returns an empty list and imports used
# only by the physical C07 modules are absent from the frozen helper.
sys.path.insert(0, BACKEND)
app_hiddenimports = [
    module
    for module in collect_submodules("app", on_error="raise")
    if module
    not in {
        "app.database._c07_fresh_source_bootstrap",
        "app.database._c07_maintenance_upgrade",
        "app.database._c07_production_migration",
        "app.database._managed_schema_upgrade",
    }
]
if "app.c07_money_facts" not in app_hiddenimports:
    raise RuntimeError("C07 frozen helper dependency discovery is incomplete")
for required_metadata_module in (
    "app.database_model_registry",
    "app.tenant_contract",
):
    if required_metadata_module not in app_hiddenimports:
        raise RuntimeError(
            f"frozen metadata dependency discovery omitted {required_metadata_module}"
        )

hiddenimports = (
    collect_submodules("uvicorn")
    + app_hiddenimports
    # PG-only (debt #4): bundle the PostgreSQL dialect + psycopg 3 binary driver.
    # SQLAlchemy's PyInstaller hook only auto-detects psycopg2, and SQLAlchemy
    # dialects load dynamically by URL scheme, so they must be named explicitly.
    # The locked Windows CI build executes the dedicated frozen C07 helper's
    # no-database release-plan mode before provenance can be published. Database
    # actions remain covered separately by the PostgreSQL release lanes.
    + collect_submodules("psycopg")
    + [
        "psycopg_binary",
        "sqlalchemy.dialects.postgresql",
        "alembic.command",
        "alembic.config",
        "alembic.context",
        "alembic.migration",
        "alembic.operations",
        "alembic.script",
        "anyio._backends._asyncio",
        "multipart",
    ]
)

datas = [
    (os.path.join(BACKEND, "app", "static"), "app/static"),
    (os.path.join(BACKEND, "app", "templates"), "app/templates"),
    # The C07 maintenance action is intentionally loaded by physical file path
    # so Python never executes app.database.__init__ and never materialises the
    # ordinary global engine/settings in the migration helper.
    (
        os.path.join(
            BACKEND,
            "app",
            "database",
            "_c07_production_migration.py",
        ),
        "app/database",
    ),
    (
        os.path.join(
            BACKEND,
            "app",
            "database",
            "_c07_fresh_source_bootstrap.py",
        ),
        "app/database",
    ),
    (
        os.path.join(
            BACKEND,
            "app",
            "database",
            "_c07_maintenance_upgrade.py",
        ),
        "app/database",
    ),
    (
        os.path.join(
            BACKEND,
            "app",
            "database",
            "_managed_schema_upgrade.py",
        ),
        "app/database",
    ),
    (os.path.join(BACKEND, "alembic.ini"), "."),
    (os.path.join(BACKEND, "migrations"), "migrations"),
]

# OCR, build tooling, and non-PostgreSQL database drivers are intentionally excluded.
# SQLAlchemy's generic PyInstaller hook otherwise bundles SQLite even though the runtime
# contract rejects every non-PostgreSQL DATABASE_URL.
excludes = [
    "rapidocr",
    "onnxruntime",
    "cv2",
    "PyInstaller",
    "pytest",
    "ruff",
    "sqlite3",
    "_sqlite3",
    "pysqlite2",
    "MySQLdb",
]

a = Analysis(
    [os.path.join(HERE, "launch.py")],
    pathex=[BACKEND],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir: binaries go into COLLECT below, not the EXE.
    name="ticketbox-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # ADR-0047 §8 service build: windowed (no console). Under a Windows service
    # there is no TTY, so sys.stdout/stderr are None. launch.py guards its startup
    # print and routes uvicorn + app logging to a rotating file under the data dir
    # (DATA_ROOT/logs), so the service has diagnostics and never crashes on a
    # None.write. Launching from a terminal still works — it just won't show a
    # console window.
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# The service executable is deliberately windowed, so it has no reliable
# stdout/stderr pipe.  The installer invokes the same frozen entry point through
# this console helper for the bounded fresh-source and production C07 actions
# whose exact typed results feed the host lifecycle coordinator. Both binaries
# share the same PYZ/Analysis and therefore the same attested migration code.
c07_migrator_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ticketbox-c07-migrator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# onedir (ADR-0047 §8): collect the binaries + datas next to the EXE into
# dist/ticketbox-backend/ (ticketbox-backend.exe + _internal/) instead of folding
# everything into a single self-extracting file.
coll = COLLECT(
    exe,
    c07_migrator_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ticketbox-backend",
)

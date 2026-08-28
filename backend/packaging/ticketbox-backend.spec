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
# only by the physical generation modules are absent from the frozen helper.
sys.path.insert(0, BACKEND)
discovered_app_modules = collect_submodules("app", on_error="raise")
retired_c07_modules = sorted(
    module
    for module in discovered_app_modules
    if module == "app.database_generation_c07_contract"
    or module.startswith("app.database._c07_")
)
retired_dataset_mutation_modules = {
    "app.dataset_maintenance_cli",
    "app.database._dataset_backup_action",
    "app.database._dataset_backup_snapshot",
    "app.database._dataset_restore_action",
    "app.database._dataset_restore_authority",
    "app.database._dataset_restore_security",
    "app.database._managed_schema_upgrade",
    "app.services.backup_service",
    "app.services.backup_job_lease",
    "app.services.dataset_backup_inventory_writer",
    "app.services.dataset_originals_adapter",
    "app.services.dataset_restore_service",
    "app.services.postgres_backup_adapter",
    "app.services.postgres_backup_validation_service",
}
if retired_c07_modules:
    raise RuntimeError(
        "retired C07 database modules returned to the frozen source graph: "
        + ", ".join(retired_c07_modules)
    )
app_hiddenimports = [
    module
    for module in discovered_app_modules
    if module
    not in {
        "app.database._database_generation_program_validation",
        "app.database._fresh_schema_upgrade",
        "app.database._database_generation_target_verification",
    }
    and module not in retired_dataset_mutation_modules
]
for required_app_module in (
    "app.app_meta_observation",
    "app.canonical_money_facts",
    "app.canonical_money_facts_contract",
    "app.database._database_generation_program",
    "app.database._database_generation_runtime_admission",
    "app.database._managed_postgres_role_authority",
    "app.database_model_registry",
    "app.database._money_schema_attestation",
    "app.database._postgres_operation_failures",
    "app.tenant_contract",
):
    if required_app_module not in app_hiddenimports:
        raise RuntimeError(
            f"frozen app dependency discovery omitted {required_app_module}"
        )

hiddenimports = (
    collect_submodules("uvicorn")
    + app_hiddenimports
    # PG-only (debt #4): bundle the PostgreSQL dialect + psycopg 3 binary driver.
    # SQLAlchemy's PyInstaller hook only auto-detects psycopg2, and SQLAlchemy
    # dialects load dynamically by URL scheme, so they must be named explicitly.
    # The locked Windows CI build executes the dedicated generation helper's
    # no-database program validation before provenance can be published.
    # Database actions remain covered separately by PostgreSQL release lanes.
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
    # Generation actions are loaded by physical file path so Python never
    # executes app.database.__init__ or materialises its runtime engine/settings.
    (
        os.path.join(
            BACKEND,
            "app",
            "database",
            "_database_generation_target_verification.py",
        ),
        "app/database",
    ),
    (
        os.path.join(
            BACKEND,
            "app",
            "database",
            "_database_generation_program_validation.py",
        ),
        "app/database",
    ),
    (
        os.path.join(
            BACKEND,
            "app",
            "database",
            "_fresh_schema_upgrade.py",
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
    *retired_c07_modules,
    *sorted(retired_dataset_mutation_modules),
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
# this console helper for build-program validation, Fresh-only schema/owner
# creation and read-only target verification. Both binaries share the same
# PYZ/Analysis and therefore the same attested generation code.
database_maintenance_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ticketbox-database-maintenance",
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
    database_maintenance_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ticketbox-backend",
)

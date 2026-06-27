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

from PyInstaller.utils.hooks import collect_submodules

HERE = SPECPATH  # injected by PyInstaller: directory of this spec (backend/packaging)
BACKEND = os.path.dirname(HERE)

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("app")
    # PG-only (debt #4): bundle the PostgreSQL dialect + psycopg 3 binary driver.
    # SQLAlchemy's PyInstaller hook only auto-detects psycopg2, and SQLAlchemy
    # dialects load dynamically by URL scheme, so they must be named explicitly.
    # NOTE: the frozen-EXE build is not exercised in CI — after changing this,
    # smoke-test scripts\build_backend_exe.ps1 output against a local PostgreSQL.
    + collect_submodules("psycopg")
    + [
        "psycopg_binary",
        "sqlalchemy.dialects.postgresql",
        "anyio._backends._asyncio",
        "multipart",
    ]
)

datas = [
    (os.path.join(BACKEND, "app", "static"), "app/static"),
    (os.path.join(BACKEND, "app", "templates"), "app/templates"),
    (os.path.join(BACKEND, "alembic.ini"), "."),
    (os.path.join(BACKEND, "migrations"), "migrations"),
]

# OCR + build tooling are intentionally excluded to keep the EXE lean.
excludes = ["rapidocr", "onnxruntime", "cv2", "PyInstaller", "pytest", "ruff"]

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

# onedir (ADR-0047 §8): collect the binaries + datas next to the EXE into
# dist/ticketbox-backend/ (ticketbox-backend.exe + _internal/) instead of folding
# everything into a single self-extracting file.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ticketbox-backend",
)

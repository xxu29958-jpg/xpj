# PyInstaller spec — frozen Ticketbox backend (no OCR; OCR is opt-in and heavy).
#
# Build from the backend/ directory:
#     .venv-build\Scripts\pyinstaller.exe packaging\ticketbox-backend.spec
# (scripts/build_backend_exe.ps1 wraps this with a clean build venv.)
#
# All paths are absolute (derived from SPECPATH = this file's dir) so the build
# is cwd-independent. Layout note: app/config.py and app/database resolve paths
# via Path(__file__).parents[N], which at runtime points at the extraction dir
# (sys._MEIPASS). So alembic.ini and migrations/ are bundled at the bundle ROOT
# (dest "." / "migrations") to match backend_root; static/templates stay under
# app/ to match Path(app/...).parent.

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
    a.binaries,
    a.datas,
    [],
    name="ticketbox-backend",
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

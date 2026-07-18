# PyInstaller spec for the ordinary-user Desktop Manager.
#
# The Manager is a separate onedir payload from the backend service. This keeps
# the host control adapter out of the FastAPI runtime while still giving Inno a
# Python-free executable to install and launch.

import os


HERE = SPECPATH
DESKTOP = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(DESKTOP)

analysis = Analysis(
    [os.path.join(DESKTOP, "backend_manager", "__main__.py")],
    pathex=[DESKTOP],
    binaries=[],
    datas=[
        (os.path.join(DESKTOP, "backend_manager", "ui.html"), "backend_manager"),
        (os.path.join(DESKTOP, "backend_manager", "product.html"), "backend_manager"),
        (os.path.join(DESKTOP, "backend_manager", "product.css"), "backend_manager"),
        (os.path.join(DESKTOP, "backend_manager", "product.js"), "backend_manager"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyInstaller", "pytest", "ruff"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ticketbox-manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(REPO_ROOT, "backend", "packaging", "ticketbox.ico"),
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ticketbox-manager",
)

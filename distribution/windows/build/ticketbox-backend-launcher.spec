# -*- mode: python -*-
# PyInstaller onefile spec：TicketboxBackendLauncher。
# Shawl 包装本 EXE；本 EXE 再按 installation.json.active_release_id 启动对应 backend。
import os

spec_dir = os.path.dirname(os.path.abspath(SPEC))
lifecycle_dir = os.path.abspath(os.path.join(spec_dir, "..", "lifecycle"))
icon_path = os.path.abspath(
    os.path.join(spec_dir, "..", "..", "..", "backend", "packaging", "ticketbox.ico")
)

a = Analysis(
    [os.path.join(lifecycle_dir, "ticketbox_backend_launcher", "__main__.py")],
    pathex=[lifecycle_dir],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TicketboxBackendLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=icon_path,
)

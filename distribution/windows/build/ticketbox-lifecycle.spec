# -*- mode: python -*-
# PyInstaller onefile spec：TicketboxLifecycle coordinator CLI。
# 这是 vNext 安装器 AfterInstall Exec 唯一入口（install / resume / inspect）。
import os

spec_dir = os.path.dirname(os.path.abspath(SPEC))
lifecycle_dir = os.path.abspath(os.path.join(spec_dir, "..", "lifecycle"))
icon_path = os.path.abspath(
    os.path.join(spec_dir, "..", "..", "..", "backend", "packaging", "ticketbox.ico")
)

a = Analysis(
    [os.path.join(lifecycle_dir, "ticketbox_lifecycle", "__main__.py")],
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
    name="TicketboxLifecycle",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    icon=icon_path,
)

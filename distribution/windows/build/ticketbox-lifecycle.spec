# -*- mode: python -*-
# PyInstaller onedir spec：elevated coordinator never extracts code into a writable temp root。
# 这是 vNext 安装器 [Run] 调用的已安装 coordinator 入口（install / resume / inspect）。
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
    [],
    exclude_binaries=True,
    name="TicketboxLifecycle",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    icon=icon_path,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TicketboxLifecycle",
)

# Independent onedir process. The parent backend excludes these native modules.
import json
import os

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

BACKEND = os.path.dirname(SPECPATH)
with open(os.path.join(BACKEND, "ocr_runtime", "recipe-v4.json"), encoding="utf-8") as stream:
    recipe = json.load(stream)

# Models are copied separately from this exact locked wheel, hash-checked against
# the source recipe, and placed beside the worker. There is no runtime download.
datas = collect_data_files("rapidocr", excludes=["models/*"])
for dependency in recipe["dependencies"]:
    datas += copy_metadata(dependency)

analysis = Analysis(
    [os.path.join(SPECPATH, "launch_ocr.py")],
    pathex=[BACKEND],
    binaries=[],
    datas=datas,
    hiddenimports=["rapidocr.inference_engine.onnxruntime"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["app", "sqlalchemy", "psycopg", "PyInstaller", "pytest", "ruff",
              "torch", "paddle", "openvino", "tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [],
    exclude_binaries=True,
    name="ticketbox-ocr",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
collection = COLLECT(
    exe, analysis.binaries, analysis.datas,
    strip=False,
    upx=False,
    name="ticketbox-ocr",
)

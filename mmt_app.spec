# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import builtins

block_cipher = None

# Base directories (robust to how the spec is invoked)
if getattr(builtins, "__spec__", None) and getattr(builtins.__spec__, "origin", None):
    project_dir = Path(builtins.__spec__.origin).resolve().parent
elif "__file__" in globals():
    project_dir = Path(__file__).resolve().parent
else:
    project_dir = Path(".").resolve()

src_dir = project_dir / "src"
main_script = src_dir / "mmt_app" / "main.py"
icon_file = (src_dir / "mmt_app" / "resources" / "appicon.ico").resolve()

datas = [(str(src_dir / "mmt_app" / "resources"), "resources")]

a = Analysis(
    [str(main_script)],
    pathex=[str(src_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtCharts", "hid"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MuscleMemoryTrainer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file),
)

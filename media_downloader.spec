# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path


def _collect_tk_assets():
    base = Path(getattr(sys, "base_prefix", sys.prefix))
    tcl_root = base / "tcl"
    dll_root = base / "DLLs"

    datas = []
    if (tcl_root / "tcl8.6" / "init.tcl").exists():
        for child in tcl_root.iterdir():
            if child.is_dir():
                datas.append((str(child), f"tcl/{child.name}"))

    binaries = []
    for dll_name in ("tcl86t.dll", "tk86t.dll"):
        dll_path = dll_root / dll_name
        if dll_path.exists():
            binaries.append((str(dll_path), "."))

    return datas, binaries


tk_datas, tk_binaries = _collect_tk_assets()


a = Analysis(
    ['gui_launcher.py'],
    pathex=[],
    binaries=tk_binaries,
    datas=[
        ('./module/templates', './module/templates'),
        ('./module/static/', './module/static'),
        *tk_datas,
    ],
    hiddenimports=['tkinter', 'tkinter.ttk', '_tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyinstaller_hooks/rthook_tkinter.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='tdl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory='.',
)

# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path


def _collect_tk_assets():
    base = Path(getattr(sys, "base_prefix", sys.prefix))
    tcl_root = base / "tcl"
    dll_root = base / "DLLs"

    datas = []
    tcl_data = tcl_root / "tcl8.6"
    tk_data = tcl_root / "tk8.6"
    if (tcl_data / "init.tcl").exists():
        datas.append((str(tcl_data), "_tcl_data"))
    if (tk_data / "tk.tcl").exists():
        datas.append((str(tk_data), "_tk_data"))

    binaries = []
    for dll_name in ("tcl86t.dll", "tk86t.dll"):
        dll_path = dll_root / dll_name
        if dll_path.exists():
            binaries.append((str(dll_path), "."))

    return datas, binaries


tk_datas, tk_binaries = _collect_tk_assets()


def _add_tkinter_pure_modules(analysis):
    base = Path(getattr(sys, "base_prefix", sys.prefix))
    tkinter_root = base / "Lib" / "tkinter"
    if not (tkinter_root / "__init__.py").exists():
        return

    existing = {entry[0] for entry in analysis.pure}
    for module_file in tkinter_root.rglob("*.py"):
        relative = module_file.relative_to(tkinter_root)
        if relative.name == "__init__.py":
            module_name = "tkinter"
            if len(relative.parts) > 1:
                module_name = "tkinter." + ".".join(relative.parts[:-1])
        else:
            module_name = "tkinter." + ".".join(relative.with_suffix("").parts)
        if module_name not in existing:
            analysis.pure.append((module_name, str(module_file), "PYMODULE"))
            existing.add(module_name)


a = Analysis(
    ['gui_launcher.py'],
    pathex=[],
    binaries=tk_binaries,
    datas=[
        ('./module/templates', './module/templates'),
        ('./module/static/', './module/static'),
        *tk_datas,
    ],
    hiddenimports=['tkinter', '_tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyinstaller_hooks/rthook_tkinter.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
_add_tkinter_pure_modules(a)
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

import os
import sys
from pathlib import Path


base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
tcl_dir = base_dir / "tcl" / "tcl8.6"
tk_dir = base_dir / "tcl" / "tk8.6"

if tcl_dir.exists():
    os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
if tk_dir.exists():
    os.environ.setdefault("TK_LIBRARY", str(tk_dir))

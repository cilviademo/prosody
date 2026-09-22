# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Prosody core.

Built as **onedir**, not onefile: onefile unpacks to %TEMP% on every launch,
adds seconds to startup and is a reliable way to get flagged by antivirus.

Built as a **console** binary so stdin/stdout exist — the shell talks to it
over stdio JSON lines. The console window never appears because the shell
spawns it with CREATE_NO_WINDOW. Do not switch this to ``console=False``: on
Windows that detaches the standard handles and the IPC dies silently.

Run from the repository root:

    python -m PyInstaller prosody-core.spec --noconfirm
"""

from pathlib import Path

ROOT = Path(SPECPATH)
PACKAGE = ROOT / "prosody_core"

# Loaded by path at runtime, so import analysis cannot see them.
datas = [
    (str(PACKAGE / "arrange" / "profiles"), "prosody_core/arrange/profiles"),
    (str(PACKAGE / "assets"), "prosody_core/assets"),
]

# importlib.metadata needs the .dist-info folder, which PyInstaller does not
# collect on its own; without it the health check reports "pyflp-unknown".
from PyInstaller.utils.hooks import copy_metadata

datas += copy_metadata("pyflp")

binaries = []

hiddenimports = [
    # Parser, and the construct-based event structs it builds lazily.
    "pyflp",
    "construct",
    # pydantic v2 keeps its validator core in a compiled module.
    "pydantic",
    "pydantic_core",
    "annotated_types",
    # MIDI export.
    "mido",
    "mido.backends",
    "mido.backends.rtmidi",
    # Imported lazily by the index and by FL discovery.
    "sqlite3",
    "winreg",
]

# numpy and soundfile are deliberately absent. Nothing in prosody_core imports
# them today — they are declared as optional extras for the preview stitcher
# that has not been built. Adding them here would put ~50 MB of unused DLLs in
# every release. When preview/stitch.py lands, add:
#     from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
#     datas += collect_data_files("soundfile", include_py_files=False)
#     binaries += collect_dynamic_libs("soundfile")   # libsndfile
#     hiddenimports += ["numpy", "soundfile"]

a = Analysis(
    [str(PACKAGE / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Pulled in transitively and never used; each costs tens of megabytes.
    excludes=[
        "tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "IPython", "pytest", "_pytest", "setuptools", "pip", "numpy",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="prosody-core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed binaries are a common antivirus trigger.
    console=True,       # Required for stdio IPC. The shell hides the window.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="prosody-core",
)

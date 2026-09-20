"""Environment discovery: FL Studio, ffmpeg, and what this machine can do.

Never assume a hardcoded install path (product brief section 20). Discovery
order on Windows is: explicit ``FLPF_FL_EXE`` override, then the registry, then
the conventional install roots, then ``PATH``.

On non-Windows hosts FL Studio is simply absent: this module reports that as a
fact rather than guessing, and the render-dependent stages stay disabled.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

FL_EXE_NAMES = ("FL64.exe", "FL.exe")

#: Conventional install roots, tried in order. Not exhaustive by design.
_WINDOWS_ROOTS = (
    r"C:\Program Files\Image-Line\FL Studio 2024",
    r"C:\Program Files\Image-Line\FL Studio 21",
    r"C:\Program Files\Image-Line\FL Studio 20",
    r"C:\Program Files (x86)\Image-Line\FL Studio 20",
)

_REGISTRY_KEYS = (
    r"SOFTWARE\Image-Line\Shared\Paths",
    r"SOFTWARE\WOW6432Node\Image-Line\Shared\Paths",
)

#: Command-line switches this project relies on. ``midi_export`` is deliberately
#: None: the switch letter is documented as existing but has not been confirmed
#: on a real install (SPEC.md section 10, EXECUTE.md T3).
FL_SWITCHES: dict[str, str | None] = {
    "render_project": "/R<file>",
    "export_formats": "/E<fmt,fmt>",
    "render_folder": "/F<folder>",
    "midi_export": None,
}


def flag(name: str) -> bool:
    """True when an FLPF_* environment flag is set to 1."""
    return os.environ.get(name, "") == "1"


@dataclass(frozen=True)
class Environment:
    platform: str
    python_version: str
    fl_executable: Path | None
    fl_discovery: str
    ffmpeg: Path | None
    pyflp_version: str
    pyflp_compat_shim: bool
    render_enabled: bool
    gui_enabled: bool

    @property
    def can_render(self) -> bool:
        return self.render_enabled and self.fl_executable is not None


def _from_registry() -> tuple[Path | None, str]:
    if sys.platform != "win32":
        return None, "not applicable (non-Windows host)"
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return None, "winreg is unavailable"

    for key_path in _REGISTRY_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "FLStudio")
        except OSError:
            continue
        for exe_name in FL_EXE_NAMES:
            candidate = Path(value) / exe_name
            if candidate.is_file():
                return candidate, f"registry: HKLM\\{key_path}"
    return None, "no Image-Line paths key in the registry"


def find_fl_executable() -> tuple[Path | None, str]:
    """Locate FL Studio.

    Returns ``(path, reason)``. When found, ``reason`` says how; when not, it
    is a bare phrase that callers compose into their own sentence - so nothing
    ends up reading "not found: not found".
    """
    override = os.environ.get("FLPF_FL_EXE")
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate, "FLPF_FL_EXE override"
        return None, f"FLPF_FL_EXE points at a missing file ({override})"

    found, how = _from_registry()
    if found is not None:
        return found, how

    for root in _WINDOWS_ROOTS:
        for exe_name in FL_EXE_NAMES:
            candidate = Path(root) / exe_name
            if candidate.is_file():
                return candidate, f"default install path: {root}"

    for exe_name in FL_EXE_NAMES:
        if located := shutil.which(exe_name):
            return Path(located), "PATH"

    if sys.platform != "win32":
        return None, f"FL Studio is Windows-only and this host is {sys.platform}"
    return None, "not in the registry, the default install folders, or PATH"


def describe(settings: Mapping[str, object] | None = None) -> Environment:
    """Describe this machine's capabilities.

    ``settings`` are the user's stored preferences. They take precedence over
    the ``FLPF_*`` environment flags, which remain the CLI's way in — without
    this the desktop Settings screen would save a preference nothing reads.
    """
    from flpfinisher.parse import _pyflp_compat
    from flpfinisher.parse.pyflp_backend import _COMPAT_APPLIED, pyflp_version

    del _pyflp_compat  # imported for its side effect ordering only

    settings = settings or {}

    configured = settings.get("fl_executable")
    if configured and Path(str(configured)).is_file():
        fl_exe: Path | None = Path(str(configured))
        how = "set in Settings"
    elif configured:
        fl_exe, how = None, f"the path set in Settings does not exist ({configured})"
    else:
        fl_exe, how = find_fl_executable()

    ffmpeg = shutil.which("ffmpeg")
    return Environment(
        platform=sys.platform,
        python_version=".".join(str(p) for p in sys.version_info[:3]),
        fl_executable=fl_exe,
        fl_discovery=how,
        ffmpeg=Path(ffmpeg) if ffmpeg else None,
        pyflp_version=pyflp_version(),
        pyflp_compat_shim=_COMPAT_APPLIED,
        render_enabled=bool(settings.get("render_enabled")) or flag("FLPF_RENDER"),
        gui_enabled=bool(settings.get("gui_stems_enabled")) or flag("FLPF_GUI"),
    )

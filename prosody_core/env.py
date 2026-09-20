"""Environment discovery: FL Studio, bundled binaries, and what this machine can do.

Never assume a hardcoded install path. Discovery order on Windows is: an
explicit override, then the registry (both hives — FL can be installed
per-user), then the conventional install roots newest-edition-first, then
``PATH``.

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

from prosody_core.fs import pe

FL_EXE_NAMES = ("FL64.exe", "FL.exe")

#: Editions newest first, so a machine with several installs offers the newest.
FL_EDITIONS = ("FL Studio 2025", "FL Studio 2024", "FL Studio 21", "FL Studio 20")

#: Program Files variants, 64-bit first.
PROGRAM_ROOTS = (r"C:\Program Files", r"C:\Program Files (x86)")

REGISTRY_KEYS = (
    r"SOFTWARE\Image-Line\Shared\Paths",
    r"SOFTWARE\WOW6432Node\Image-Line\Shared\Paths",
)

#: Command-line switches this project relies on. ``midi_export`` is deliberately
#: None: the switch letter is documented as existing but has not been confirmed
#: on a real install.
FL_SWITCHES: dict[str, str | None] = {
    "render_project": "/R<file>",
    "export_formats": "/E<fmt,fmt>",
    "render_folder": "/F<folder>",
    "midi_export": None,
}


def windows_install_roots() -> tuple[str, ...]:
    """Conventional FL install folders, newest edition first."""
    return tuple(
        f"{root}\\Image-Line\\{edition}"
        for edition in FL_EDITIONS
        for root in PROGRAM_ROOTS
    )


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
    #: Architecture of the configured FL executable, for the UI to report.
    #: None when no FL is configured or it could not be read.
    fl_architecture: str | None = None
    #: False only when FL is configured and is *not* a 64-bit Windows program.
    fl_architecture_ok: bool = True
    #: Safe Mode: inspect and browse only. Nothing is written and nothing is
    #: launched (HARDENING P0.2).
    safe_mode: bool = False

    @property
    def can_render(self) -> bool:
        return (
            self.render_enabled
            and self.fl_executable is not None
            and self.fl_architecture_ok
            and not self.safe_mode
        )


# --------------------------------------------------------------------------- #
# Bundled binaries
# --------------------------------------------------------------------------- #


def bundled_bin_dir() -> Path | None:
    """``resources/bin`` beside the packaged core, when running from a bundle.

    PyInstaller onedir puts the core at
    ``<app>/resources/prosody-core/prosody-core.exe``, so sibling resources sit
    one level up.
    """
    override = os.environ.get("PROSODY_BIN")
    if override and Path(override).is_dir():
        return Path(override)
    if getattr(sys, "frozen", False):
        core_dir = Path(sys.executable).resolve().parent
        candidate = core_dir.parent / "bin"
        if candidate.is_dir():
            return candidate
    return None


def safe_mode() -> bool:
    """Whether this session may only look, never touch.

    The shell decides (a --safe argument, a safemode.flag beside the
    executable, or Shift held at launch) and tells the core through the
    environment, so there is one answer for the whole process tree.
    """
    return os.environ.get("PROSODY_SAFE_MODE", "") == "1"


def find_ffmpeg() -> Path | None:
    """Prefer a bundled ffmpeg over whatever happens to be on PATH.

    A release must not depend on the user's PATH, and must not silently run a
    different build than the one it was tested against.
    """
    bin_dir = bundled_bin_dir()
    if bin_dir:
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = bin_dir / name
            if candidate.is_file():
                return candidate
    located = shutil.which("ffmpeg")
    return Path(located) if located else None


# --------------------------------------------------------------------------- #
# FL Studio discovery
# --------------------------------------------------------------------------- #


def _from_registry() -> tuple[Path | None, str]:
    """Look in both HKLM and HKCU — FL can be installed per-user."""
    if sys.platform != "win32":
        return None, "not applicable (non-Windows host)"
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return None, "winreg is unavailable"

    hives = (
        ("HKLM", winreg.HKEY_LOCAL_MACHINE),
        ("HKCU", winreg.HKEY_CURRENT_USER),
    )
    for hive_name, hive in hives:
        for key_path in REGISTRY_KEYS:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, "FLStudio")
            except OSError:
                continue
            for exe_name in FL_EXE_NAMES:
                candidate = Path(value) / exe_name
                if candidate.is_file():
                    return candidate, f"registry: {hive_name}\\{key_path}"
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

    for root in windows_install_roots():
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
    from prosody_core.parse import _pyflp_compat
    from prosody_core.parse.pyflp_backend import _COMPAT_APPLIED, pyflp_version

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

    # A path that exists is not yet a program that can run. Reading two fields
    # of the PE header here turns "the render failed" into "that file is
    # 32-bit" (HARDENING P0.1).
    # Checked on every platform, not just Windows: the logic is identical, and
    # gating it on the host meant the Linux test suite could not see it. It
    # didn't, either — a fixture writing an empty file named FL64.exe passed
    # here and failed on the Windows runner.
    architecture: str | None = None
    architecture_ok = True
    if fl_exe is not None:
        architecture_ok, architecture = pe.describe(fl_exe)
        if not architecture_ok:
            how = f"{how}, but it is {architecture}"

    return Environment(
        platform=sys.platform,
        python_version=".".join(str(p) for p in sys.version_info[:3]),
        fl_executable=fl_exe,
        fl_discovery=how,
        ffmpeg=find_ffmpeg(),
        pyflp_version=pyflp_version(),
        pyflp_compat_shim=_COMPAT_APPLIED,
        render_enabled=bool(settings.get("render_enabled")) or flag("FLPF_RENDER"),
        gui_enabled=bool(settings.get("gui_stems_enabled")) or flag("FLPF_GUI"),
        fl_architecture=architecture,
        fl_architecture_ok=architecture_ok,
        safe_mode=safe_mode(),
    )

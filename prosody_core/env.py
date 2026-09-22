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
#: Known editions, newest first. Discovery no longer depends on this list —
#: it globs ``Image-Line\*`` — but the list still seeds the search order and
#: documents what has been seen. FL Studio 2026 was missing from it, which is
#: how the studio PC's install went undetected (TESTING_HANDOFF P0.3).
FL_EDITIONS = (
    "FL Studio 2026", "FL Studio 2025", "FL Studio 2024", "FL Studio 21", "FL Studio 20",
)

#: Program Files variants, 64-bit first.
PROGRAM_ROOTS = (r"C:\Program Files", r"C:\Program Files (x86)")

REGISTRY_KEYS = (
    r"SOFTWARE\Image-Line\Shared\Paths",
    r"SOFTWARE\WOW6432Node\Image-Line\Shared\Paths",
)
#: Roots walked recursively for any value that points at an FL install.
REGISTRY_ROOTS = (r"SOFTWARE\Image-Line", r"SOFTWARE\WOW6432Node\Image-Line")
_REGISTRY_MAX_KEYS = 400
_REGISTRY_MAX_DEPTH = 6

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
    #: FL64.exe's own version resource, e.g. ``2026.1.0.4321``. None off Windows.
    fl_file_version: str | None = None

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


def _edition_number(folder: Path) -> tuple[int, ...]:
    """``FL Studio 2026`` → ``(2026,)``; ``FL Studio 21`` → ``(21,)``."""
    digits = "".join(ch if ch.isdigit() else " " for ch in folder.name).split()
    return tuple(int(d) for d in digits[:1])


def file_version(path: Path) -> str | None:
    """The executable's own version string (Windows only), e.g. ``2026.1.0.4321``.

    Read from the PE version resource, which is what FL's About box shows and
    what a per-version switch table has to key on.
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        import struct as _struct
        from ctypes import wintypes

        ver = ctypes.WinDLL("version", use_last_error=True)  # type: ignore[attr-defined]
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return None
        ptr, length = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None
        info = ctypes.string_at(ptr, length.value)
        ms, ls = _struct.unpack_from("<II", info, 8)
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:  # noqa: BLE001 - a missing version is cosmetic
        return None


@dataclass(frozen=True)
class FLCandidate:
    path: Path
    source: str
    version: str | None

    @property
    def rank(self) -> tuple[int, ...]:
        parsed = tuple(int(x) for x in (self.version or "").split(".") if x.isdigit())
        return parsed or _edition_number(self.path.parent)


def _registry_candidates() -> list[FLCandidate]:
    """Every install path the Image-Line registry tree mentions, in any hive.

    Walked recursively because the layout is not documented and changed with
    the year-numbered editions; any string value that names an existing folder
    holding FL64.exe, or the executable itself, counts.
    """
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return []

    found: dict[Path, FLCandidate] = {}
    visited = 0

    def walk(hive: int, hive_name: str, key_path: str, depth: int) -> None:
        nonlocal visited
        if depth > _REGISTRY_MAX_DEPTH or visited > _REGISTRY_MAX_KEYS:
            return
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            return
        visited += 1
        with key:
            i = 0
            while True:
                try:
                    _name, value, kind = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not value:
                    continue
                text = os.path.expandvars(str(value)).strip().strip('"')
                candidate = Path(text)
                exes = [candidate] if candidate.suffix.lower() == ".exe" else [
                    candidate / n for n in FL_EXE_NAMES
                ]
                for exe in exes:
                    if exe.name in FL_EXE_NAMES and exe.is_file() and exe not in found:
                        found[exe] = FLCandidate(exe, f"registry: {hive_name}\\{key_path}", file_version(exe))
            j = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, j)
                except OSError:
                    break
                j += 1
                walk(hive, hive_name, f"{key_path}\\{sub}", depth + 1)

    for hive_name, hive in (("HKLM", winreg.HKEY_LOCAL_MACHINE), ("HKCU", winreg.HKEY_CURRENT_USER)):
        for root in REGISTRY_ROOTS:
            walk(hive, hive_name, root, 0)
    return list(found.values())


def discover_fl_candidates(
    program_roots: tuple[str, ...] | None = None,
) -> tuple[FLCandidate, ...]:
    """Every FL Studio on this machine, newest first.

    Globs ``<Program Files>\\Image-Line\\*`` for any edition rather than checking
    a list of names, then adds whatever the registry names. Ranked by the
    executable's file version, falling back to the year or major in the folder
    name, so several installs offer the newest.
    """
    roots = program_roots if program_roots is not None else PROGRAM_ROOTS
    found: dict[Path, FLCandidate] = {}
    for root in roots:
        base = Path(root) / "Image-Line"
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir()):
            if not folder.is_dir():
                continue
            for exe_name in FL_EXE_NAMES:
                exe = folder / exe_name
                if exe.is_file() and exe not in found:
                    found[exe] = FLCandidate(exe, f"install folder: {folder}", file_version(exe))
                    break
    for cand in _registry_candidates():
        found.setdefault(cand.path, cand)
    return tuple(sorted(found.values(), key=lambda c: c.rank, reverse=True))


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

    candidates = discover_fl_candidates()
    if candidates:
        best = candidates[0]
        others = ", ".join(c.path.parent.name for c in candidates[1:])
        how = best.source
        if best.version:
            how += f" (v{best.version})"
        if others:
            how += f"; also found: {others}"
        return best.path, how

    found, how = _from_registry()
    if found is not None:
        return found, how

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
        fl_file_version=file_version(fl_exe) if fl_exe is not None else None,
    )

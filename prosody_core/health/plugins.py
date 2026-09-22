"""Which referenced plugins FL Studio knows about, from FL's own records.

HARDENING P1.6: plugin states are REFERENCED, DETECTED, UNKNOWN or
FAILED_IN_RENDER, and FL Studio is the authority — Prosody never marks a plugin
MISSING on its own. FL keeps a record of every plugin it has scanned under
``Documents\\Image-Line\\FL Studio\\Presets\\Plugin database\\Installed`` as one
``.nfo`` (and ``.fst``) per plugin, named for the plugin. Matching a project's
plugin names against those files is a check FL itself would agree with.

TESTING_HANDOFF P1.3: the health row said "not checkable without FL Studio on
this machine" while FL was configured. It is checkable; this checks it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PluginState(str, Enum):
    REFERENCED = "REFERENCED"      # in the project; nothing checked
    DETECTED = "DETECTED"          # FL's plugin database knows it
    UNKNOWN = "UNKNOWN"            # not in the database; FL decides at render


@dataclass(frozen=True)
class PluginVerdict:
    name: str
    state: PluginState
    detail: str = ""


def plugin_database_dir() -> Path | None:
    """FL's ``Plugin database\\Installed`` folder, or None when absent."""
    # Imported here: workspace imports the health package, and a module-level
    # import the other way would be a cycle.
    from prosody_core.workspace import documents_dir

    override = os.environ.get("PROSODY_FL_PLUGIN_DB")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_dir() else None
    candidate = documents_dir() / "Image-Line" / "FL Studio" / "Presets" / "Plugin database" / "Installed"
    return candidate if candidate.is_dir() else None


def _normalise(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def scan_database(root: Path) -> set[str]:
    """Normalised plugin names FL has recorded, from ``.nfo``/``.fst`` stems."""
    names: set[str] = set()
    for p in Path(root).rglob("*"):
        if p.suffix.lower() in (".nfo", ".fst") and p.is_file():
            names.add(_normalise(p.stem))
    return names


def detect(plugin_names: tuple[str, ...], database: Path | None = None) -> tuple[PluginVerdict, ...]:
    """A verdict per referenced plugin. REFERENCED for all when no database."""
    root = database if database is not None else plugin_database_dir()
    if root is None:
        return tuple(PluginVerdict(n, PluginState.REFERENCED, "FL's plugin database was not found") for n in plugin_names)
    known = scan_database(root)
    out: list[PluginVerdict] = []
    for name in plugin_names:
        key = _normalise(name)
        # FL's file may carry a vendor suffix ("Serum (Xfer Records)"); a
        # prefix match keeps that from reading as unknown.
        hit = key in known or any(k.startswith(key) or key.startswith(k) for k in known if k)
        out.append(
            PluginVerdict(name, PluginState.DETECTED, "in FL's plugin database")
            if hit else
            PluginVerdict(name, PluginState.UNKNOWN, "not in FL's plugin database; FL decides at render")
        )
    return tuple(out)

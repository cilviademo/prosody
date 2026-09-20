"""Where Prosody keeps its files.

Everything generated lives under one workspace the user can move, never beside
the user's source projects. Default: ``Documents/Prosody``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Prosody"
SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS: dict[str, object] = {
    "fl_executable": None,
    "export_root": None,
    "audio_format": "wav",
    "wav_bit_depth": 24,
    "creativity_level": 0,
    "ai_provider": "rules",
    "structure": "balanced",
    "render_enabled": False,
    "gui_stems_enabled": False,
}


def documents_dir() -> Path:
    if sys.platform == "win32":
        profile = os.environ.get("USERPROFILE")
        if profile:
            return Path(profile) / "Documents"
    return Path.home() / "Documents"


def default_root() -> Path:
    override = os.environ.get("PROSODY_HOME")
    if override:
        return Path(override)
    return documents_dir() / APP_NAME


@dataclass(frozen=True)
class Workspace:
    """The application's folders. Created on demand, never scattered."""

    root: Path

    @classmethod
    def open(cls, root: Path | None = None) -> Workspace:
        workspace = cls(Path(root) if root else default_root())
        workspace.ensure()
        return workspace

    def ensure(self) -> None:
        for directory in (
            self.projects, self.cache, self.exports, self.logs, self.database
        ):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def projects(self) -> Path:
        return self.root / "Projects"

    @property
    def cache(self) -> Path:
        return self.root / "Cache"

    @property
    def exports(self) -> Path:
        return self.root / "Exports"

    @property
    def logs(self) -> Path:
        return self.root / "Logs"

    @property
    def database(self) -> Path:
        return self.root / "Database"

    @property
    def db_path(self) -> Path:
        return self.database / "library.db"

    @property
    def settings_path(self) -> Path:
        return self.root / SETTINGS_FILE

    # -- settings ---------------------------------------------------------- #

    def load_settings(self) -> dict[str, object]:
        settings = dict(DEFAULT_SETTINGS)
        if self.settings_path.is_file():
            try:
                stored = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return settings
            settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
        return settings

    def save_settings(self, settings: dict[str, object]) -> dict[str, object]:
        merged = self.load_settings()
        merged.update({k: v for k, v in settings.items() if k in DEFAULT_SETTINGS})
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(merged, indent=2) + "\n", encoding="utf-8"
        )
        return merged

    def export_root(self) -> Path:
        configured = self.load_settings().get("export_root")
        if configured:
            return Path(str(configured))
        return self.exports

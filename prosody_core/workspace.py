"""Where Prosody keeps its files.

Two roots, deliberately separated:

* **Documents root** — ``Documents/Prosody/{Exports,Projects}``. The user's
  output. Visible, backed up, safe to move.
* **State root** — ``%LOCALAPPDATA%\\Prosody\\{prosody.db,settings.json,Cache,Logs}``.
  Machine-local bookkeeping nobody should have to look at, and which should not
  end up in a cloud-synced Documents folder where two machines would fight over
  one SQLite file.

In **portable mode** both collapse into ``<exe dir>\\Data`` so a USB stick
carries everything and nothing is written to the host profile. The desktop
shell decides the mode and passes the roots through the environment; the core
never guesses when it has been told.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Prosody"
SETTINGS_FILE = "settings.json"
DB_FILE = "prosody.db"

#: Set by the desktop shell. Either may be absent when the core runs standalone.
ENV_HOME = "PROSODY_HOME"     # documents root
ENV_STATE = "PROSODY_STATE"   # app-state root

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
    "window": None,
    #: The last Test Connection: exe, its size/mtime, pass/fail, when, detail.
    #: "FL Studio ready" requires a pass against the executable that is still
    #: there (TESTING_HANDOFF P1.1).
    "fl_test": None,
    #: The user has seen the synced-folder notice and chosen to keep exporting
    #: there (TESTING_HANDOFF P1.4).
    "cloud_export_acknowledged": False,
}


def documents_dir() -> Path:
    """The user's Documents folder — the *real* one.

    On Windows that is a known folder, and OneDrive redirects it to
    ``<OneDrive>\\Documents`` while ``%USERPROFILE%\\Documents`` keeps existing
    as an empty decoy. The registry says where it actually is.
    """
    override = os.environ.get("PROSODY_DOCUMENTS")
    if override:
        return Path(override)
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "Personal")
            expanded = Path(os.path.expandvars(str(value)))
            if expanded.is_dir():
                return expanded
        except OSError:
            pass
        profile = os.environ.get("USERPROFILE")
        if profile:
            return Path(profile) / "Documents"
    return Path.home() / "Documents"


def default_user_root() -> Path:
    """Where ``Prosody\\{Exports,Projects}`` goes when nothing is configured.

    Documents, unless Documents is inside a sync client's folder: stems are
    large, sync clients lock files they are uploading, and a user's renders
    should not race their cloud quota (TESTING_HANDOFF P1.4). Then it is
    ``<profile>\\Prosody``, which no client syncs.
    """
    from prosody_core.fs.source import cloud_sync_provider

    documents = documents_dir()
    if cloud_sync_provider(documents):
        return Path.home() / "Prosody"
    return documents / "Prosody"


def local_app_data() -> Path:
    """Per-user, machine-local application data."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local)
        return Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def default_root() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override)
    return default_user_root()


def default_state() -> Path:
    override = os.environ.get(ENV_STATE)
    if override:
        return Path(override)
    return local_app_data() / APP_NAME


@dataclass(frozen=True)
class Workspace:
    """The application's folders. Created on demand, never scattered."""

    root: Path
    state: Path

    @classmethod
    def open(cls, root: Path | None = None, state: Path | None = None) -> Workspace:
        """Open a workspace.

        Naming a ``root`` without a ``state`` means "everything here": state
        follows the root rather than falling back to the machine-wide
        location. Anything else is a footgun — a caller that points the
        workspace somewhere specific and still gets the shared database is
        surprised exactly once, in production.
        """
        if root is not None and state is None:
            resolved_root = Path(root)
            resolved_state = resolved_root
        else:
            resolved_root = Path(root) if root else default_root()
            resolved_state = Path(state) if state else default_state()

        workspace = cls(resolved_root, resolved_state)
        workspace.ensure()
        return workspace

    @classmethod
    def portable(cls, data_dir: Path) -> Workspace:
        """Everything under one folder, for a self-contained copy."""
        data = Path(data_dir)
        return cls.open(root=data, state=data)

    def ensure(self) -> None:
        for directory in (
            self.projects, self.exports, self.cache, self.logs, self.database
        ):
            directory.mkdir(parents=True, exist_ok=True)

    # -- user output ------------------------------------------------------- #

    @property
    def projects(self) -> Path:
        return self.root / "Projects"

    @property
    def exports(self) -> Path:
        return self.root / "Exports"

    # -- machine-local state ----------------------------------------------- #

    @property
    def cache(self) -> Path:
        return self.state / "Cache"

    @property
    def logs(self) -> Path:
        return self.state / "Logs"

    @property
    def database(self) -> Path:
        return self.state

    @property
    def db_path(self) -> Path:
        return self.state / DB_FILE

    @property
    def settings_path(self) -> Path:
        return self.state / SETTINGS_FILE

    @property
    def is_portable(self) -> bool:
        return self.root == self.state

    # -- settings ---------------------------------------------------------- #

    def load_settings(self) -> dict[str, object]:
        settings = dict(DEFAULT_SETTINGS)
        if self.settings_path.is_file():
            try:
                stored = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return settings
            if isinstance(stored, dict):
                settings.update(
                    {k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}
                )
        return settings

    def save_settings(self, settings: dict[str, object]) -> dict[str, object]:
        merged = self.load_settings()
        merged.update({k: v for k, v in settings.items() if k in DEFAULT_SETTINGS})
        self.state.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(merged, indent=2) + "\n", encoding="utf-8"
        )
        return merged

    def export_root(self) -> Path:
        configured = self.load_settings().get("export_root")
        if configured:
            return Path(str(configured))
        return self.exports

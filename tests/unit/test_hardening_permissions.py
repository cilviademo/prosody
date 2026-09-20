"""HARDENING P0.6: the webview is granted nothing, and paths are untrusted."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prosody_core.api import MAX_SOURCE_BYTES, validate_source_path

REPO = Path(__file__).resolve().parent.parent.parent
TAURI = REPO / "apps" / "desktop" / "src-tauri"


def _capabilities() -> dict:
    return json.loads((TAURI / "capabilities" / "default.json").read_text(encoding="utf-8"))


def test_the_webview_has_no_shell_permission():
    granted = _capabilities()["permissions"]
    assert not [p for p in granted if str(p).startswith("shell:")], (
        "a shell permission lets the frontend run programs; every spawn "
        "belongs in a Rust command that validates its arguments"
    )


def test_the_webview_has_no_filesystem_permission():
    granted = _capabilities()["permissions"]
    assert not [p for p in granted if str(p).startswith("fs:")], (
        "the frontend must reach the disk only through Rust commands"
    )


def test_the_webview_cannot_open_an_arbitrary_path():
    """opener:default covers urls and reveal-in-dir; allow-open-path does not
    belong here — nothing in the frontend calls the plugin, and Rust's own
    call is a free function that no capability gates."""
    granted = _capabilities()["permissions"]
    assert "opener:allow-open-path" not in granted
    assert "opener:allow-open-url" not in granted


def test_the_content_security_policy_allows_no_remote_code():
    conf = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    csp = conf["app"]["security"]["csp"]
    assert csp, "there is no CSP at all"

    directives = {
        part.strip().split(" ", 1)[0]: part.strip()
        for part in csp.split(";")
        if part.strip()
    }
    assert directives["default-src"] == "default-src 'self'"
    assert directives["script-src"] == "script-src 'self'"
    assert directives["object-src"] == "object-src 'none'"
    for name, directive in directives.items():
        if name in {"img-src", "media-src"}:
            continue  # asset: and data: are needed to show a render
        assert "http://" not in directive.replace("http://ipc.localhost", ""), (
            f"{name} allows a remote origin: {directive}"
        )
        assert "https://" not in directive, f"{name} allows a remote origin: {directive}"
        assert "'unsafe-eval'" not in directive


# --- dropped paths are untrusted input -------------------------------------- #

def test_a_real_project_passes(tmp_path):
    path = tmp_path / "Starfall.flp"
    path.write_bytes(b"FLhd" + b"\x00" * 100)
    assert validate_source_path(path) == path


def test_a_folder_dropped_instead_of_a_file_is_refused(tmp_path):
    folder = tmp_path / "My Beats"
    folder.mkdir()
    with pytest.raises(ValueError, match="folder"):
        validate_source_path(folder)


def test_a_missing_path_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_source_path(tmp_path / "gone.flp")


def test_a_wav_dropped_by_mistake_is_refused(tmp_path):
    path = tmp_path / "Kick.wav"
    path.write_bytes(b"RIFF")
    with pytest.raises(ValueError, match=r"\.flp"):
        validate_source_path(path)


def test_an_empty_file_is_refused(tmp_path):
    path = tmp_path / "empty.flp"
    path.touch()
    with pytest.raises(ValueError, match="empty"):
        validate_source_path(path)


def test_an_absurdly_large_file_is_refused_without_reading_it(tmp_path):
    """A sparse file stands in for the 4 GB WAV someone renames to .flp."""
    path = tmp_path / "huge.flp"
    with path.open("wb") as handle:
        handle.truncate(MAX_SOURCE_BYTES + 1)
    with pytest.raises(ValueError, match="far larger"):
        validate_source_path(path)


def test_an_unreadable_file_is_refused_before_parsing(tmp_path, monkeypatch):
    path = tmp_path / "locked.flp"
    path.write_bytes(b"FLhd" + b"\x00" * 100)

    real_open = Path.open

    def deny(self, *args, **kwargs):
        if self == path:
            raise PermissionError("used by another process")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(ValueError, match="could not be read"):
        validate_source_path(path)


def test_every_handler_that_takes_a_path_validates_it():
    """A new handler must not be able to skip the check by accident."""
    import inspect

    from prosody_core import api

    for name in ("h_inspect", "h_build", "h_plan"):
        source = inspect.getsource(getattr(api, name))
        assert "validate_source_path" in source, f"{name} takes a path without validating it"


# --- P1.5: no capability claim is hardcoded in the frontend ------------------ #

UI = REPO / "apps" / "desktop" / "src"


def test_the_ui_never_hardcodes_a_reason_a_capability_is_unavailable():
    """The backend knows why; the frontend must not guess.

    "needs FL Studio" was hardcoded on the WAV and MP3 toggles, which was
    wrong whenever the real cause was Safe Mode, a 32-bit FL, or rendering
    simply switched off — and it sent the user to fix the wrong thing.
    """
    invented = [
        '"needs FL Studio"',
        '"unavailable"',
        '"Requires FL Studio"',
        '"not configured"',
    ]
    offenders: list[str] = []
    for tsx in UI.rglob("*.tsx"):
        text = tsx.read_text(encoding="utf-8")
        for phrase in invented:
            if phrase in text:
                offenders.append(f"{tsx.relative_to(UI)}: {phrase}")
    assert not offenders, (
        "a capability reason is written into the interface instead of read "
        "from runtime detection:\n  " + "\n  ".join(offenders)
    )


def test_the_capability_flags_the_ui_reads_all_come_from_the_environment():
    """Each flag must exist in the environment payload, or the UI shows undefined."""
    import inspect

    from prosody_core import api

    source = inspect.getsource(api.h_environment)
    for field in ("canRender", "renderReason", "stemStrategy", "stemReason", "safeMode"):
        assert f'"{field}"' in source, f"the UI reads {field} but the backend never sends it"

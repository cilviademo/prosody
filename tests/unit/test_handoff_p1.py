"""TESTING_HANDOFF P1: truth, correctness, safety — as tests, not intentions."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from prosody_core.api import HANDLERS
from prosody_core.fs import source as source_module
from prosody_core.fs.safety import sha256_file
from prosody_core.fs.source import atomic_write, cloud_sync_provider, stale_partials
from prosody_core.health import plugins
from prosody_core.health.check import check_project
from prosody_core.model.schemas import PluginRef
from prosody_core.parse.pyflp_backend import PyFLPBackend
from prosody_core.validate.roundtrip import round_trip
from prosody_core.workspace import Workspace, default_user_root, documents_dir
from tests.fixtures.projects import audio_clip_session, full_kit

# --- P1.3: plugins_available asks FL's own records ---------------------------- #

@pytest.fixture
def plugin_db(tmp_path: Path) -> Path:
    root = tmp_path / "Plugin database" / "Installed"
    (root / "Generators" / "VST3").mkdir(parents=True)
    (root / "Generators" / "Fruity").mkdir(parents=True)
    (root / "Generators" / "VST3" / "Ripchord.nfo").write_text("x")
    (root / "Generators" / "VST3" / "Ripchord.fst").write_bytes(b"x")
    (root / "Generators" / "Fruity" / "Fruity Kick.nfo").write_text("x")
    (root / "Generators" / "VST3" / "Serum (Xfer Records).nfo").write_text("x")
    return root


def test_plugins_in_fls_database_are_detected_and_others_are_unknown_not_missing(plugin_db):
    verdicts = {v.name: v for v in plugins.detect(("Ripchord", "fruity kick", "Serum", "Kontakt"), plugin_db)}
    assert verdicts["Ripchord"].state is plugins.PluginState.DETECTED
    assert verdicts["fruity kick"].state is plugins.PluginState.DETECTED, "case must not matter"
    assert verdicts["Serum"].state is plugins.PluginState.DETECTED, "a vendor suffix in FL's file must still match"
    assert verdicts["Kontakt"].state is plugins.PluginState.UNKNOWN
    assert "MISSING" not in verdicts["Kontakt"].state.value, "FL is the authority; never MISSING"


def test_without_a_database_plugins_are_only_referenced(tmp_path, monkeypatch):
    monkeypatch.setenv("PROSODY_FL_PLUGIN_DB", str(tmp_path / "nowhere"))
    assert all(v.state is plugins.PluginState.REFERENCED for v in plugins.detect(("Ripchord",)))


def test_the_health_row_reports_the_database_verdict(make_flp, plugin_db):
    project = PyFLPBackend().parse(make_flp(full_kit()))
    with_plugins = project.model_copy(update={"plugins": (
        PluginRef(name="Ripchord", used_by_channels=(3,)),
        PluginRef(name="Kontakt", used_by_channels=(4,)),
    )})
    row = next(c for c in check_project(with_plugins, plugin_database=plugin_db).checks
               if c.name == "plugins_available")
    assert row.ok is None
    assert "1 of 2" in row.detail and "Kontakt" in row.detail and "FL decides" in row.detail

    all_known = project.model_copy(update={"plugins": (PluginRef(name="Ripchord", used_by_channels=(3,)),)})
    row = next(c for c in check_project(all_known, plugin_database=plugin_db).checks
               if c.name == "plugins_available")
    assert row.ok is True


# --- P1.3: write_compatibility is answered for the file in hand ---------------- #

def test_every_fixture_round_trips_byte_for_byte(all_fixture_flps):
    for name, path in all_fixture_flps.items():
        trip = round_trip(path)
        assert trip.ok is True and trip.byte_identical, f"{name}: {trip.detail}"


def test_the_health_row_is_now_a_verdict_not_a_deferral(make_flp):
    path = make_flp(full_kit())
    project = PyFLPBackend().parse(path)
    row = next(c for c in check_project(project, source=path).checks if c.name == "write_compatibility")
    assert row.ok is True
    assert "byte for byte" in row.detail
    assert "not yet run" not in row.detail


def test_a_damaged_file_gets_a_failing_verdict(make_flp):
    path = make_flp(full_kit())
    path.write_bytes(path.read_bytes()[:-30])
    assert round_trip(path).ok is False


# --- P1.4: synced folders ------------------------------------------------------ #

def test_cloud_sync_is_recognised_by_the_clients_own_variable(tmp_path, monkeypatch):
    onedrive = tmp_path / "OD-root"
    (onedrive / "Documents").mkdir(parents=True)
    monkeypatch.setenv("OneDrive", str(onedrive))
    assert cloud_sync_provider(onedrive / "Documents" / "Prosody") == "OneDrive"
    assert cloud_sync_provider(tmp_path / "elsewhere") is None


def test_cloud_sync_is_recognised_by_a_path_component(monkeypatch):
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    assert cloud_sync_provider(Path("C:/Users/marcm/OneDrive - Contoso/Desktop/Prosody")) == "OneDrive"
    assert cloud_sync_provider(Path("/Users/x/Dropbox/Beats")) == "Dropbox"
    assert cloud_sync_provider(Path("/home/user/Documents")) is None


def test_the_default_root_avoids_a_synced_documents_folder(tmp_path, monkeypatch):
    synced = tmp_path / "OneDrive" / "Documents"
    synced.mkdir(parents=True)
    monkeypatch.setenv("PROSODY_DOCUMENTS", str(synced))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "profile"))
    assert documents_dir() == synced
    assert default_user_root() == tmp_path / "profile" / "Prosody"

    plain = tmp_path / "Documents"
    plain.mkdir()
    monkeypatch.setenv("PROSODY_DOCUMENTS", str(plain))
    assert default_user_root() == plain / "Prosody"


def test_a_transient_lock_on_the_destination_is_ridden_out(tmp_path, monkeypatch):
    """OneDrive holds a file for a moment after it appears; the rename waits."""
    monkeypatch.setattr(source_module, "_REPLACE_BACKOFF", 0.0)
    real = os.replace
    failures = {"left": 2}

    def flaky(src, dst, *a, **k):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError("The process cannot access the file")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", flaky)
    out = atomic_write(tmp_path / "Full.wav", b"audio")
    assert out.read_bytes() == b"audio"
    assert stale_partials(tmp_path) == []


def test_a_lock_that_never_lifts_still_raises_and_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(source_module, "_REPLACE_BACKOFF", 0.0)
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(PermissionError("locked")))
    with pytest.raises(PermissionError):
        atomic_write(tmp_path / "Full.wav", b"audio")
    assert not (tmp_path / "Full.wav").exists()
    assert stale_partials(tmp_path) == []


def test_the_portable_project_zip_is_written_whole_or_not_at_all(make_flp, tmp_path):
    from prosody_core.extract.package import package_project

    path = make_flp(full_kit())
    project = PyFLPBackend().parse(path)
    dest = tmp_path / "out" / "Starfall.zip"
    package_project(path, project, dest)
    assert zipfile.ZipFile(dest).testzip() is None
    assert stale_partials(tmp_path) == []


def test_the_environment_reports_a_synced_export_root_and_a_local_alternative(tmp_path, monkeypatch):
    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    synced = tmp_path / "OneDrive" / "Desktop" / "Prosody"
    synced.mkdir(parents=True)
    workspace.save_settings({"export_root": str(synced)})
    env = HANDLERS["environment"]({}, workspace)
    assert env["exportRootCloud"] == "OneDrive"
    assert env["suggestedExportRoot"].endswith(os.path.join("Prosody", "Exports"))
    assert "OneDrive" not in env["suggestedExportRoot"]


# --- P1.5: missing samples ------------------------------------------------------ #

def test_locate_finds_samples_by_name_and_changes_nothing(make_flp, tmp_path):
    from tests.fixtures.projects import full_kit as kit

    path = make_flp(kit())
    before = sha256_file(path)
    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    view = HANDLERS["project.inspect"]({"path": str(path)}, workspace)
    assert view["missingSamples"], "the fixture's samples should be missing here"

    root = tmp_path / "Samples"
    (root / "Kits" / "909").mkdir(parents=True)
    (root / "Kits" / "909" / "Kick_01.wav").write_bytes(b"RIFF")
    (root / "Other" / "Snare21.wav").parent.mkdir(parents=True)
    (root / "Other" / "Snare21.wav").write_bytes(b"RIFF")

    result = HANDLERS["samples.locate"]({"root": str(root), "samples": view["missingSamples"]}, workspace)
    by = {r["original"]: r for r in result["results"]}
    assert result["found"] == 2
    assert by["D:\\Drums\\Kick_01.wav"]["state"] == "RELOCATED"
    assert by["D:\\Drums\\Kick_01.wav"]["candidates"][0].endswith("Kick_01.wav")
    assert by["D:\\Drums\\HH_closed.wav"]["state"] == "MISSING"
    assert sha256_file(path) == before, "locating must never write to the project"
    assert HANDLERS["project.inspect"]({"path": str(path)}, workspace)["missingSamples"] == view["missingSamples"]


def test_a_render_with_missing_samples_is_marked_incomplete_not_failed(make_flp, tmp_path, monkeypatch):
    from prosody_core.extract import render_fl

    path = make_flp(full_kit())
    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    monkeypatch.setattr(render_fl, "availability", lambda env: (True, "stand-in"))

    def fake_render(target, out_dir, *, formats, env, timeout):
        out_dir.mkdir(parents=True, exist_ok=True)
        wav = out_dir / "Full.wav"
        wav.write_bytes(b"RIFF")
        return render_fl.RenderResult(ok=True, outputs=[wav], seconds=1.0, command=["fl"])

    monkeypatch.setattr(render_fl, "render_project", fake_render)
    result = HANDLERS["build.run"]({"path": str(path), "genre": "rnb", "wav": True, "mp3": False}, workspace)
    stage = next(s for s in result["stages"] if s["name"] == "Rendering audio")
    assert stage["status"] == "warning"
    assert "incomplete: 3 samples missing" in stage["detail"]


# --- P1.6: an audio-clip session says what it is ----------------------------------- #

def test_an_audio_clip_session_is_not_arrangeable_and_says_why(make_flp, tmp_path):
    path = make_flp(audio_clip_session())
    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    view = HANDLERS["project.inspect"]({"path": str(path)}, workspace)
    assert view["canArrange"] is False
    assert view["counts"]["patterns"] == 0
    assert view["audioClipCount"] == 2

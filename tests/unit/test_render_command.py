"""The FL command line, as FL Studio actually documents it.

TESTING_HANDOFF P0.2: on the studio PC, Test Connection reported "FL Studio
exited cleanly but produced no files (exit 0)". The command never named the
project — it passed the output path where the project belongs. These tests
pin the documented form and the output discovery that goes with it.
"""

from __future__ import annotations

import struct
from pathlib import Path

from prosody_core.api import HANDLERS
from prosody_core.extract import render_fl
from tests.fixtures.binaries import fake_fl
from tests.unit.test_extract import offline_env


def _wav(path: Path, seconds: float, *, rate: int = 44100, channels: int = 2, bits: int = 24) -> Path:
    frames = int(seconds * rate)
    data = b"\x00" * (frames * channels * (bits // 8))
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * bits // 8, channels * bits // 8, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def _fl_that_renders_beside_the_project(seconds: float = 2.05):
    """A stand-in for FL64.exe: writes <project>.wav next to the project."""
    calls: list[list[str]] = []

    def run(command, timeout):
        calls.append(list(command))
        project = Path(command[-1])
        _wav(project.with_suffix(".wav"), seconds)
        return 0, "", "", 1.5

    return run, calls


def test_the_command_names_the_project_last_and_never_the_output(tmp_path, monkeypatch):
    fl = fake_fl(tmp_path)
    run, calls = _fl_that_renders_beside_the_project()
    monkeypatch.setattr(render_fl, "_run", run)
    project = tmp_path / "work" / "loop.flp"
    project.parent.mkdir()
    project.write_bytes(b"FLhd")

    result = render_fl.render_project(
        project, tmp_path / "out", env=offline_env(fl_executable=fl, render_enabled=True)
    )

    assert calls == [[str(fl), "/R", "/Ewav", str(project)]]
    assert result.ok, result.message
    assert not any(arg.startswith("/R") and len(arg) > 2 for arg in calls[0]), "the old /R<path> form"


def test_output_written_beside_the_project_is_moved_into_the_export_folder(tmp_path, monkeypatch):
    fl = fake_fl(tmp_path)
    run, _ = _fl_that_renders_beside_the_project()
    monkeypatch.setattr(render_fl, "_run", run)
    project = tmp_path / "work" / "loop.flp"
    project.parent.mkdir()
    project.write_bytes(b"FLhd")
    out = tmp_path / "out"

    result = render_fl.render_project(project, out, env=offline_env(fl_executable=fl, render_enabled=True))

    assert [p.parent for p in result.outputs] == [out]
    assert result.outputs[0].name == "loop.wav"
    assert not (project.parent / "loop.wav").exists(), "left beside the project"


def test_a_file_that_was_already_there_is_not_reported_as_a_render(tmp_path, monkeypatch):
    fl = fake_fl(tmp_path)
    monkeypatch.setattr(render_fl, "_run", lambda c, t: (0, "", "", 0.1))
    project = tmp_path / "work" / "loop.flp"
    project.parent.mkdir()
    project.write_bytes(b"FLhd")
    _wav(project.parent / "old.wav", 1.0)

    result = render_fl.render_project(project, tmp_path / "out", env=offline_env(fl_executable=fl, render_enabled=True))
    assert result.outputs == []
    assert result.ok is False


def test_wav_duration_is_read_from_riff_headers_for_formats_the_stdlib_refuses(tmp_path):
    assert abs(render_fl.wav_duration_seconds(_wav(tmp_path / "a.wav", 2.0, bits=24)) - 2.0) < 1e-6
    assert abs(render_fl.wav_duration_seconds(_wav(tmp_path / "b.wav", 0.5, bits=32)) - 0.5) < 1e-6
    junk = tmp_path / "c.wav"
    junk.write_bytes(b"not a wav")
    assert render_fl.wav_duration_seconds(junk) is None


def test_test_connection_checks_the_rendered_length_and_reports_the_command(tmp_path, monkeypatch):
    fl = fake_fl(tmp_path)
    run, _ = _fl_that_renders_beside_the_project(seconds=2.05)
    monkeypatch.setattr(render_fl, "_run", run)

    result = render_fl.test_connection(offline_env(fl_executable=fl, render_enabled=False), timeout=5)
    assert result.ok, result.detail
    assert result.expected == 2.0
    assert result.duration is not None and abs(result.duration - 2.05) < 0.01
    assert "expected about 2.0 s" in result.detail
    assert result.command[:3] == [str(fl), "/R", "/Ewav"]


def test_test_connection_fails_when_fl_rendered_far_too_little(tmp_path, monkeypatch):
    fl = fake_fl(tmp_path)
    run, _ = _fl_that_renders_beside_the_project(seconds=0.3)
    monkeypatch.setattr(render_fl, "_run", run)
    result = render_fl.test_connection(offline_env(fl_executable=fl, render_enabled=True), timeout=5)
    assert result.ok is False
    assert "shorter" in result.detail


def test_test_connection_can_use_the_users_own_project(tmp_path, monkeypatch):
    fl = fake_fl(tmp_path)
    run, calls = _fl_that_renders_beside_the_project()
    monkeypatch.setattr(render_fl, "_run", run)
    own = tmp_path / "loop_test.flp"
    own.write_bytes(b"FLhd")

    result = render_fl.test_connection(offline_env(fl_executable=fl, render_enabled=True), timeout=5, project=own)
    assert result.ok
    assert result.expected is None
    assert Path(calls[0][-1]).name == "loop_test.flp"
    assert Path(calls[0][-1]) != own, "the original must be copied, never rendered in place"


def test_ready_requires_a_passing_test_against_the_same_executable(tmp_path, monkeypatch):
    """TESTING_HANDOFF P1.1: the header went green after a failed Test."""
    from prosody_core.workspace import Workspace

    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    fl = fake_fl(tmp_path)
    workspace.save_settings({"fl_executable": str(fl), "render_enabled": True})

    assert HANDLERS["environment"]({}, workspace)["renderTested"] is False

    monkeypatch.setattr(render_fl, "_run", lambda c, t: (0, "", "", 0.2))       # exit 0, no file
    failed = HANDLERS["fl.test"]({}, workspace)
    assert failed["ok"] is False
    assert HANDLERS["environment"]({}, workspace)["renderTested"] is False

    run, _ = _fl_that_renders_beside_the_project()
    monkeypatch.setattr(render_fl, "_run", run)
    passed = HANDLERS["fl.test"]({}, workspace)
    assert passed["ok"] is True and passed["command"]
    assert HANDLERS["environment"]({}, workspace)["renderTested"] is True

    # A different executable at the same path (an update) invalidates the pass.
    fl.write_bytes(fl.read_bytes() + b"\x00" * 16)
    assert HANDLERS["environment"]({}, workspace)["renderTested"] is False

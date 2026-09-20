"""HARDENING P1.1 and P1.3: never collapse evidence into "success"."""

from __future__ import annotations

import json
from pathlib import Path

import mido
import pytest

from prosody_core.api import HANDLERS
from prosody_core.model.schemas import ValidationLevel
from prosody_core.validate import midi_check
from prosody_core.workspace import Workspace
from tests.fixtures.projects import full_kit


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path / "docs", tmp_path / "state")


# --- P1.1: the ladder ------------------------------------------------------- #

def test_a_good_derivative_reaches_structural_validation(workspace, make_flp):
    source = make_flp(full_kit())
    result = HANDLERS["build.run"](
        {"path": str(source), "genre": "rnb", "arrange": True}, workspace
    )
    report = json.loads(
        (Path(result["outDir"]) / "reports" / "validation.json").read_text(encoding="utf-8")
    )
    assert report["passed"] is True
    assert report["level"] == ValidationLevel.STRUCTURALLY_VALIDATED.value


def test_the_level_says_why_it_went_no_higher(workspace, make_flp):
    """A level the build cannot reach must be explained, not silently omitted."""
    source = make_flp(full_kit())
    result = HANDLERS["build.run"](
        {"path": str(source), "genre": "rnb", "arrange": True}, workspace
    )
    report = json.loads(
        (Path(result["outDir"]) / "reports" / "validation.json").read_text(encoding="utf-8")
    )
    detail = report["level_detail"]
    assert "independent parser" in detail, detail
    assert "FL Studio" in detail, detail


def test_an_unvalidated_derivative_is_kept_out_of_exports(workspace, make_flp, monkeypatch):
    """Deleting it destroys the evidence; shipping it is worse."""
    from prosody_core import build as build_module
    from prosody_core.model.schemas import HealthCheck, ValidationResult

    source = make_flp(full_kit())

    def always_fails(src, dest, original, plan, backend, *, source_hash):
        return ValidationResult(
            project_id=original.id, passed=False,
            checks=(HealthCheck(name="notes_preserved", ok=False, detail="invented"),),
            level=ValidationLevel.FAILED, level_detail="failed: notes_preserved",
        )

    monkeypatch.setattr(build_module, "validate_derivative", always_fails)
    result = HANDLERS["build.run"](
        {"path": str(source), "genre": "rnb", "arrange": True}, workspace
    )

    out_dir = Path(result["outDir"])
    assert not list(out_dir.glob("*.flp")), "an unvalidated project reached Exports"

    kept = list((workspace.cache / "unvalidated").glob("*.unvalidated.flp"))
    assert kept, "the unvalidated file was destroyed instead of kept for investigation"
    assert kept[0].stat().st_size > 0

    stage = next(s for s in result["stages"] if s["name"] == "Writing FL Studio project")
    assert stage["status"] == "warning"
    assert "notes_preserved" in stage["detail"]


# --- P1.3: MIDI verification ------------------------------------------------ #

def _midi(path: Path, notes: list[tuple[int, int, int]]) -> Path:
    midi = mido.MidiFile()
    track = mido.MidiTrack()
    midi.tracks.append(track)
    last = 0
    for tick, pitch, velocity in notes:
        track.append(mido.Message("note_on", note=pitch, velocity=velocity, time=tick - last))
        track.append(mido.Message("note_off", note=pitch, velocity=0, time=48))
        last = tick + 48
    midi.save(str(path))
    return path


def test_a_matching_file_verifies(tmp_path):
    expected = [(0, 60, 100), (96, 64, 90)]
    path = _midi(tmp_path / "a.mid", expected)
    result = midi_check.verify(path, expected)
    assert result.ok, result.detail
    assert result.note_count == 2


@pytest.mark.parametrize(
    ("expected", "fragment"),
    [
        ([(0, 60, 100)], "1 in the project"),
        ([(0, 60, 100), (96, 67, 90)], "pitches differ"),
        ([(0, 60, 100), (192, 64, 90)], "positions differ"),
        ([(0, 60, 100), (96, 64, 30)], "velocities differ"),
    ],
)
def test_a_mismatched_file_fails_with_the_reason(tmp_path, expected, fragment):
    path = _midi(tmp_path / "a.mid", [(0, 60, 100), (96, 64, 90)])
    result = midi_check.verify(path, expected)
    assert result.ok is False
    assert fragment in result.detail


def test_a_truncated_file_fails_rather_than_raising(tmp_path):
    path = tmp_path / "bad.mid"
    path.write_bytes(b"MThd\x00\x00")
    result = midi_check.reopens(path)
    assert result.ok is False
    assert "could not be reopened" in result.detail


def test_a_missing_file_fails(tmp_path):
    result = midi_check.reopens(tmp_path / "gone.mid")
    assert result.ok is False
    assert "was not written" in result.detail


def test_a_note_on_with_zero_velocity_is_not_counted_as_a_note(tmp_path):
    """It is a note-off by convention; counting it would inflate every total."""
    path = tmp_path / "a.mid"
    midi = mido.MidiFile()
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.Message("note_on", note=60, velocity=100, time=0))
    track.append(mido.Message("note_on", note=60, velocity=0, time=48))
    midi.save(str(path))
    assert midi_check.reopens(path).note_count == 1


def test_the_build_verifies_every_midi_file_it_writes(workspace, make_flp):
    source = make_flp(full_kit())
    result = HANDLERS["build.run"](
        {"path": str(source), "genre": "rnb", "arrange": True, "midi": True}, workspace
    )
    report = json.loads(
        (Path(result["outDir"]) / "reports" / "midi-verification.json").read_text(encoding="utf-8")
    )
    assert report, "no MIDI verification was recorded"
    assert all(entry["ok"] for entry in report), report

    stage = next(s for s in result["stages"] if s["name"] == "Exporting MIDI")
    assert stage["status"] == "ok"
    assert "verified" in stage["detail"]

"""The native reader: a second parser that owes PyFLP nothing.

TESTING_HANDOFF P0.1. On the studio PC, PyFLP 2.2.1 failed on a project saved
by FL Studio 2026 with a UTF-16 decode error. These tests prove the fallback
reads what PyFLP reads on every fixture, survives what broke PyFLP, and tells
the user which reader produced the result.
"""

from __future__ import annotations

import pytest

from prosody_core.api import HANDLERS
from prosody_core.parse import native_backend as nb
from prosody_core.parse.native_backend import (
    NativeBackend,
    fl_version_of,
    newer_than_pyflp_supports,
)
from prosody_core.parse.pyflp_backend import PyFLPBackend
from prosody_core.write.eventstream import MalformedFLP, read_flp
from tests.fixtures.flp_builder import build_flp
from tests.fixtures.projects import fl2026_loop


def _shape(project):
    """Everything the product consumes, in a form that compares."""
    return {
        "tempo": project.tempo, "ppq": project.ppq, "ts": project.time_signature,
        "title": project.title, "version": project.fl_version,
        "channels": [
            (c.index, c.name, c.kind.value, c.sample_path, c.mixer_track, c.enabled)
            for c in project.channels
        ],
        "patterns": [
            (p.index, p.name, p.length_ticks,
             tuple((n.channel, n.position, n.length, n.key, n.velocity, n.pan) for n in p.notes))
            for p in project.patterns
        ],
        "clips": [
            (a.index, c.track, c.kind, c.pattern, c.channel, c.start_ticks, c.length_ticks)
            for a in project.arrangements for c in a.clips
        ],
        "tracks": [
            (a.index, t.index, t.name, t.clip_count) for a in project.arrangements for t in a.tracks
        ],
        "mixer_names": [m.name for m in project.mixer],
        "samples": [(s.path, tuple(s.used_by_channels)) for s in project.samples],
    }


def test_the_native_reader_agrees_with_pyflp_on_every_fixture(all_fixture_flps):
    """Same file, two readers, one answer — or the fallback is worthless."""
    for name, path in all_fixture_flps.items():
        pyflp_view = _shape(PyFLPBackend().parse(path))
        native_view = _shape(NativeBackend().parse(path))
        assert native_view == pyflp_view, f"readers disagree on {name}"


def test_the_native_reader_reads_an_fl_2026_shaped_loop(make_flp):
    project = NativeBackend().parse(make_flp(fl2026_loop()))
    assert project.backend == "native"
    assert project.fl_version == "2026.1.0.4321"
    assert project.tempo == 128.0
    assert len(project.patterns) == 2
    assert all(p.notes for p in project.patterns)
    assert {c.name for c in project.channels} == {"Kick", "Keys"}
    assert project.unknown_event_ids == ()
    codes = {w.code for w in project.parse_warnings}
    assert "fl_version_newer" in codes
    assert "native_backend" in codes


def test_pyflp_failure_falls_back_instead_of_failing(make_flp, monkeypatch):
    """The exact shape of the studio-PC failure, reproduced at the seam."""
    import pyflp

    path = make_flp(fl2026_loop())

    def explode(_path):
        raise UnicodeDecodeError(
            "utf-16-le", b"n?\xe7 L\x00o\x00o\x00p\x00", 0, 1, "truncated data"
        )

    monkeypatch.setattr(pyflp, "parse", explode)
    project = PyFLPBackend().parse(path)

    assert project.backend == "native (pyflp failed)"
    assert project.tempo == 128.0 and len(project.patterns) == 2
    codes = {w.code: w for w in project.parse_warnings}
    assert "pyflp_failed" in codes
    assert "UnicodeDecodeError" in codes["pyflp_failed"].message
    assert codes["pyflp_failed"].severity.value == "info", "the raw exception is diagnostics, not a headline"
    assert "fl_version_newer" in codes
    assert "2026.1.0.4321" in codes["fl_version_newer"].message
    assert "20.9" in codes["fl_version_newer"].message


def test_a_fallback_read_project_can_be_arranged(make_flp, monkeypatch, tmp_path):
    """The acceptance in the handoff: BPM, patterns with notes, Arrange enabled."""
    import pyflp

    from prosody_core.workspace import Workspace

    path = make_flp(fl2026_loop())
    monkeypatch.setattr(pyflp, "parse", lambda _p: (_ for _ in ()).throw(ValueError("boom")))
    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")

    view = HANDLERS["project.inspect"]({"path": str(path)}, workspace)
    assert view["tempo"] == 128.0
    assert view["counts"]["patterns"] == 2
    assert view["canArrange"] is True
    assert view["backend"].startswith("native")
    assert any(w["code"] == "pyflp_failed" for w in view["warnings"])

    plan = HANDLERS["arrange.plan"]({"path": str(path), "genre": "rnb"}, workspace)
    assert plan


def test_a_newer_project_read_by_pyflp_still_gets_the_version_warning(make_flp):
    """PyFLP may parse an FL 2026 file without raising and still miss things."""
    project = PyFLPBackend().parse(make_flp(fl2026_loop()))
    assert project.backend.startswith("pyflp")
    assert any(w.code == "fl_version_newer" for w in project.parse_warnings)


def test_a_file_neither_reader_can_open_is_still_a_parse_error(tmp_path):
    from prosody_core.parse.adapter import ParseError

    junk = tmp_path / "junk.flp"
    junk.write_bytes(b"not an flp at all")
    with pytest.raises(ParseError):
        PyFLPBackend().parse(junk)


# --- version, read before anything else ------------------------------------- #

def test_fl_version_is_readable_from_the_header_alone(make_flp):
    assert fl_version_of(make_flp(fl2026_loop())) == "2026.1.0.4321"


def test_fl_version_of_a_non_project_is_none(tmp_path):
    p = tmp_path / "x.flp"
    p.write_bytes(b"RIFF....")
    assert fl_version_of(p) is None


@pytest.mark.parametrize(
    ("version", "newer"),
    [("2026.1.0.4321", True), ("2024.1.1.4234", True), ("21.2.3.4004", True),
     ("20.9.2.2963", False), ("20.8.4.2576", False), ("12.5.1.5", False), (None, False)],
)
def test_newer_than_pyflp_supports(version, newer):
    assert newer_than_pyflp_supports(version) is newer


# --- tolerance --------------------------------------------------------------- #

def test_a_truncated_file_is_read_as_far_as_it_goes(tmp_path):
    whole = build_flp(fl2026_loop())
    cut = tmp_path / "cut.flp"
    cut.write_bytes(whole[:-40])

    with pytest.raises(MalformedFLP):
        read_flp(cut)                       # the writer must still refuse it
    flp = read_flp(cut, strict=False)
    assert flp.truncated_by > 0
    project = NativeBackend().parse(cut)
    assert any(w.code == "file_truncated" for w in project.parse_warnings)
    assert project.tempo == 128.0


def test_the_channel_kind_table_matches_pyflp():
    """If PyFLP's ChannelType ever renumbers, this must fail loudly."""
    from pyflp.channel import ChannelType

    from prosody_core.model.schemas import ChannelKind

    expected = {
        "Sampler": ChannelKind.SAMPLER, "Native": ChannelKind.PLUGIN,
        "Layer": ChannelKind.LAYER, "Instrument": ChannelKind.PLUGIN,
        "Automation": ChannelKind.AUTOMATION,
    }
    for member in ChannelType:
        assert member.name in expected, f"PyFLP has a ChannelType this table does not: {member.name}"
        assert nb._KIND_BY_TYPE.get(int(member)) is expected[member.name], member


# --- the paste-back diagnostic ---------------------------------------------- #

def test_the_event_inventory_names_what_pyflp_knows_and_shows_no_private_data(make_flp, tmp_path):
    from prosody_core.parse.events_dump import as_text, inventory
    from prosody_core.workspace import Workspace

    path = make_flp(fl2026_loop())
    inv = inventory(path)
    rows = {r["id"]: r for r in inv["events"]}
    assert rows[231]["name"] == "DisplayGroupID.Name"
    assert rows[231]["count"] == 2
    assert rows[231]["preview"] == "Unsorted"
    assert inv["flVersion"] == "2026.1.0.4321"
    assert inv["newerThanPyflpSupports"] is True
    assert inv["unknownToPyflp"] == []
    assert 196 not in {r["id"] for r in inv["events"] if r["preview"]}, "sample paths must not be previewed"

    text = as_text(inv)
    assert "FL version: 2026.1.0.4321" in text
    assert "newer than PyFLP" in text
    assert "Kick.wav" not in text and "D:\\" not in text

    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    via_api = HANDLERS["project.events"]({"path": str(path)}, workspace)
    assert via_api["report"].startswith("PROSODY EVENT INVENTORY")


def test_the_cli_exposes_both_the_dump_and_the_native_reader(make_flp):
    from typer.testing import CliRunner

    from prosody_core.cli import app

    path = make_flp(fl2026_loop())
    runner = CliRunner()
    dump = runner.invoke(app, ["events", str(path)])
    assert dump.exit_code == 0, dump.output
    assert "EVENT INVENTORY" in dump.output
    native = runner.invoke(app, ["inspect", str(path), "--backend", "native"])
    assert native.exit_code == 0, native.output

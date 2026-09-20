"""Parser tests against real .flp binaries produced by the fixture builder.

These are unit-tier because they need no corpus and no FL Studio, but they do
exercise the actual FLP container rather than a mock.
"""

from pathlib import Path

import pytest
from fixtures.flp_builder import (
    ChannelSpec,
    NoteSpec,
    PatternSpec,
    arranged_project,
    empty_project,
    missing_sample_project,
    multi_pattern_loop,
    odd_time_signature,
    one_pattern_loop,
)

from prosody_core.model.schemas import ChannelKind, Severity
from prosody_core.parse.adapter import ParseError, ParserBackend
from prosody_core.parse.pyflp_backend import PyFLPBackend


@pytest.fixture
def backend() -> PyFLPBackend:
    return PyFLPBackend()


def test_backend_satisfies_the_protocol(backend):
    assert isinstance(backend, ParserBackend)
    assert backend.name.startswith("pyflp-")


def test_header_fields(backend, make_flp):
    project = backend.parse(make_flp(one_pattern_loop()))
    assert project.fl_version == "21.2.3.4004"
    assert project.tempo == 140.0
    assert project.ppq == 96
    assert project.time_signature == (4, 4)
    assert project.title == "One Pattern"


def test_id_is_the_sha256_of_the_source(backend, make_flp):
    from prosody_core.fs.safety import sha256_file

    path = make_flp(one_pattern_loop())
    assert backend.parse(path).id == sha256_file(path)


def test_channels(backend, make_flp):
    project = backend.parse(make_flp(multi_pattern_loop()))
    assert [c.name for c in project.channels] == ["Kick", "Rhodes Chords"]
    assert project.channels[0].kind is ChannelKind.SAMPLER
    assert project.channels[0].mixer_track == 1
    assert project.channels[0].enabled is True


def test_patterns_and_notes(backend, make_flp):
    project = backend.parse(make_flp(multi_pattern_loop()))
    assert [p.name for p in project.patterns] == ["Drums", "Chords"]
    drums, chords = project.patterns
    assert drums.note_count == 16
    assert chords.note_count == 12
    assert project.note_count == 28


def test_note_keys_survive_pyflps_name_formatting(backend, make_flp):
    """PyFLP exposes key as 'C5'; the domain model stores FL's 0-131 number."""
    spec = one_pattern_loop()
    spec.patterns = [
        PatternSpec(
            iid=1, name="Keys",
            notes=(
                NoteSpec(position=0, length=96, key=60),
                NoteSpec(position=96, length=96, key=61),
                NoteSpec(position=192, length=96, key=0),
                NoteSpec(position=288, length=96, key=131),
            ),
        )
    ]
    notes = backend.parse(make_flp(spec)).patterns[0].notes
    assert [n.key for n in notes] == [60, 61, 0, 131]


def test_note_position_length_and_velocity(backend, make_flp):
    notes = backend.parse(make_flp(one_pattern_loop())).patterns[0].notes
    assert notes[0].position == 0
    assert notes[1].position == 96
    assert all(n.length == 48 for n in notes)
    assert all(n.velocity == 100 for n in notes)


def test_playlist_clips(backend, make_flp):
    project = backend.parse(make_flp(multi_pattern_loop()))
    clips = project.arrangements[0].clips
    assert len(clips) == 2
    assert {c.pattern for c in clips} == {1, 2}
    assert {c.track for c in clips} == {0, 1}
    assert all(c.kind == "pattern" for c in clips)
    assert all(c.length_ticks == 96 * 16 for c in clips)


def test_mixer_inserts(backend, make_flp):
    project = backend.parse(make_flp(multi_pattern_loop()))
    assert [i.name for i in project.mixer] == ["Master", "Drums", "Keys"]


def test_length_comes_from_the_playlist_when_one_exists(backend, make_flp):
    project = backend.parse(make_flp(arranged_project()))
    assert project.length_bars == 16.0
    assert len(project.arrangements[0].clips) == 4


def test_odd_time_signature_is_preserved(backend, make_flp):
    project = backend.parse(make_flp(odd_time_signature()))
    assert project.time_signature == (7, 4)
    assert project.length_bars == pytest.approx(16 / 7)


def test_samples_are_resolved_against_the_filesystem(backend, make_flp, tmp_path):
    real = tmp_path / "Kick.wav"
    real.write_bytes(b"RIFF")
    spec = one_pattern_loop()
    spec.channels = [
        ChannelSpec(name="Kick", sample_path=str(real)),
        ChannelSpec(name="Snare", sample_path="Z:\\nope\\Snare.wav"),
    ]
    project = backend.parse(make_flp(spec))
    found = {s.path: s.found for s in project.samples}
    assert found[str(real)] is True
    assert found["Z:\\nope\\Snare.wav"] is False


def test_missing_sample_fixture(backend, make_flp):
    project = backend.parse(make_flp(missing_sample_project()))
    assert len(project.samples) == 1
    assert project.samples[0].found is False


def test_source_file_is_not_modified(backend, make_flp):
    from prosody_core.fs.safety import sha256_file

    path = make_flp(multi_pattern_loop())
    before = sha256_file(path)
    backend.parse(path)
    assert sha256_file(path) == before


# -- graceful degradation --------------------------------------------------- #

def test_empty_project_degrades_instead_of_raising(backend, make_flp):
    """PyFLP raises KeyError iterating a project with no channels. The adapter
    must turn that into a warning and still return a usable BeatProject."""
    project = backend.parse(make_flp(empty_project()))
    assert project.channels == ()
    assert project.patterns == ()
    codes = {w.code for w in project.parse_warnings}
    assert "channels" in codes
    assert project.tempo == 140.0  # header still read


def test_missing_mixer_params_is_informational_not_a_warning(backend, make_flp):
    project = backend.parse(make_flp(one_pattern_loop()))
    notes = [w for w in project.parse_warnings if w.code == "mixer_slots_undescribable"]
    assert len(notes) == 1
    assert notes[0].severity is Severity.INFO


def test_warnings_are_deduplicated(backend, make_flp):
    spec = multi_pattern_loop()
    spec.mixer_names = [f"Insert {i}" for i in range(12)]
    project = backend.parse(make_flp(spec))
    codes = [w.code for w in project.parse_warnings]
    assert codes.count("mixer_slots_undescribable") == 1


def test_a_corrupt_file_raises_parse_error(backend, tmp_path: Path):
    bad = tmp_path / "corrupt.flp"
    bad.write_bytes(b"NOTANFLP" + b"\x00" * 64)
    with pytest.raises(ParseError) as exc:
        backend.parse(bad)
    assert "corrupt.flp" in str(exc.value)


def test_a_truncated_file_raises_parse_error(backend, make_flp):
    path = make_flp(one_pattern_loop())
    path.write_bytes(path.read_bytes()[:30])
    with pytest.raises(ParseError):
        backend.parse(path)


def test_every_named_fixture_parses(backend, all_fixture_flps):
    for name, path in all_fixture_flps.items():
        project = backend.parse(path)
        assert project.id, name
        assert project.fl_version, name


def test_a_windows_sample_path_survives_parsing_byte_for_byte(backend, make_flp):
    """FL writes native Windows paths; the report must echo what it stored.

    PyFLP hands back a pathlib.Path, and str() on a Path renders the *host's*
    separators. A fixture written with forward slashes therefore came back as
    'D:/Drums/Kick.wav' on Linux and 'D:\\Drums\\Kick.wav' on Windows — the
    suite was green here and red on the Windows runner. The invariant worth
    asserting is not a separator style but that nothing is rewritten.
    """
    stored = "D:\\Samples\\Kits\\909\\Kick 01.wav"
    spec = one_pattern_loop()
    spec.channels = [ChannelSpec(name="Kick", sample_path=stored)]
    project = backend.parse(make_flp(spec))

    assert [s.path for s in project.samples] == [stored]
    assert project.channels[0].sample_path == stored

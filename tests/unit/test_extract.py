"""MIDI export, packaging, stems and the FL render wrapper."""

import zipfile

import pytest

from prosody_core.classify.signals import analyse_project
from prosody_core.env import Environment
from prosody_core.extract import render_fl
from prosody_core.extract.midi import write_role_midi
from prosody_core.extract.package import package_project
from prosody_core.extract.stems import (
    GuiExportStrategy,
    SoloCopyStrategy,
    available_strategy,
    solo_copy,
)
from prosody_core.health.check import classify_state
from prosody_core.parse.pyflp_backend import PyFLPBackend
from tests.fixtures.projects import full_kit


@pytest.fixture
def backend():
    return PyFLPBackend()


@pytest.fixture
def kit(backend, make_flp):
    source = make_flp(full_kit(), "Starfall.flp")
    project = backend.parse(source)
    return source, project, analyse_project(project, classify_state(project))


def offline_env(**kw) -> Environment:
    base = {
        "platform": "linux", "python_version": "3.12.0", "fl_executable": None,
        "fl_discovery": "FL Studio is Windows-only and this host is linux",
        "ffmpeg": None, "pyflp_version": "2.2.1",
        "pyflp_compat_shim": True, "render_enabled": False, "gui_enabled": False,
    }
    base.update(kw)
    return Environment(**base)


# -- MIDI ------------------------------------------------------------------- #

def test_one_midi_file_per_role(kit, tmp_path):
    _, project, analysis = kit
    files = write_role_midi(project, analysis, tmp_path / "midi")
    names = sorted(f.name for f in files)
    assert any("Kick" in n for n in names)
    assert any("Chords" in n for n in names)
    assert len(files) == len({f.stem.split("_", 1)[1] for f in files})


def test_midi_files_are_numbered_in_role_order(kit, tmp_path):
    _, project, analysis = kit
    files = write_role_midi(project, analysis, tmp_path / "midi")
    prefixes = [int(f.name[:2]) for f in files]
    assert prefixes == sorted(prefixes) == list(range(1, len(files) + 1))


def test_midi_uses_the_project_ppq_and_tempo(kit, tmp_path):
    import mido

    _, project, analysis = kit
    files = write_role_midi(project, analysis, tmp_path / "midi")
    midi = mido.MidiFile(str(files[0]))
    assert midi.ticks_per_beat == project.ppq
    tempos = [m for t in midi.tracks for m in t if m.type == "set_tempo"]
    assert tempos and round(mido.tempo2bpm(tempos[0].tempo)) == round(project.tempo)


def test_midi_note_count_matches_the_source(kit, tmp_path):
    import mido

    _, project, analysis = kit
    files = write_role_midi(project, analysis, tmp_path / "midi")
    exported = 0
    for path in files:
        for track in mido.MidiFile(str(path)).tracks:
            exported += sum(1 for m in track if m.type == "note_on" and m.velocity > 0)
    assert exported == project.note_count


def test_midi_events_are_ordered_and_non_negative(kit, tmp_path):
    import mido

    _, project, analysis = kit
    for path in write_role_midi(project, analysis, tmp_path / "midi"):
        for track in mido.MidiFile(str(path)).tracks:
            assert all(m.time >= 0 for m in track)


def test_a_project_with_no_notes_writes_no_midi(backend, make_flp, tmp_path):
    from tests.fixtures.projects import no_notes

    project = backend.parse(make_flp(no_notes()))
    analysis = analyse_project(project, classify_state(project))
    assert write_role_midi(project, analysis, tmp_path / "midi") == []


# -- packaging -------------------------------------------------------------- #

def test_zip_contains_the_project(kit, tmp_path):
    source, project, _ = kit
    report = package_project(source, project, tmp_path / "out.zip")
    with zipfile.ZipFile(report.path) as archive:
        assert source.name in archive.namelist()


def test_missing_samples_are_listed_inside_the_zip(kit, tmp_path):
    source, project, _ = kit
    report = package_project(source, project, tmp_path / "out.zip")
    assert report.samples_missing
    with zipfile.ZipFile(report.path) as archive:
        listed = archive.read("MISSING_SAMPLES.txt").decode()
    for path in report.samples_missing:
        assert path in listed


def test_resolvable_samples_are_bundled(backend, make_flp, tmp_path):
    from tests.fixtures.flp_builder import ChannelSpec

    real = tmp_path / "Kick.wav"
    real.write_bytes(b"RIFFfake")
    spec = full_kit()
    spec.channels = [ChannelSpec("Kick", 1, str(real))]
    source = make_flp(spec, "WithSample.flp")
    project = backend.parse(source)

    report = package_project(source, project, tmp_path / "out.zip")
    assert report.samples_included == 1
    with zipfile.ZipFile(report.path) as archive:
        assert "Samples/Kick.wav" in archive.namelist()


def test_extra_files_are_included(kit, tmp_path):
    source, project, _ = kit
    extra = tmp_path / "arrangement.json"
    extra.write_text("{}")
    report = package_project(
        source, project, tmp_path / "out.zip", extra={"arrangement.json": extra}
    )
    with zipfile.ZipFile(report.path) as archive:
        assert "arrangement.json" in archive.namelist()


# -- stems ------------------------------------------------------------------ #

def test_solo_copy_enables_only_the_requested_channels(kit, backend, tmp_path):
    source, _, _ = kit
    out = solo_copy(source, tmp_path / "kick.flp", {0})
    rebuilt = backend.parse(out)
    enabled = {c.index for c in rebuilt.channels if c.enabled}
    assert enabled == {0}


def test_solo_copy_preserves_all_musical_content(kit, backend, tmp_path):
    source, project, _ = kit
    rebuilt = backend.parse(solo_copy(source, tmp_path / "s.flp", {2}))
    assert rebuilt.note_count == project.note_count
    assert len(rebuilt.patterns) == len(project.patterns)
    assert len(rebuilt.channels) == len(project.channels)


def test_solo_copy_never_touches_the_source(kit, tmp_path):
    from prosody_core.fs.safety import sha256_file

    source, _, _ = kit
    before = sha256_file(source)
    solo_copy(source, tmp_path / "s.flp", {0})
    assert sha256_file(source) == before


def test_no_stem_strategy_is_available_without_fl_studio():
    strategy, reason = available_strategy(offline_env())
    assert strategy is None
    assert "FL Studio not found" in reason


def test_solo_copy_reports_why_it_cannot_run():
    ok, reason = SoloCopyStrategy().available(offline_env())
    assert not ok and reason


def test_gui_export_declares_itself_unimplemented_rather_than_guessing():
    ok, reason = GuiExportStrategy().available(
        offline_env(gui_enabled=True, fl_executable=__import__("pathlib").Path(__file__))
    )
    assert not ok
    assert "not implemented" in reason


def test_stems_never_fabricate_audio(kit, tmp_path):
    _, project, analysis = kit
    result = SoloCopyStrategy().render(
        tmp_path / "x.flp", project, analysis, tmp_path / "stems", env=offline_env()
    )
    assert not result.ok
    assert result.stems == []


# -- FL render wrapper ------------------------------------------------------ #

def test_render_is_unavailable_without_fl_studio():
    ok, reason = render_fl.availability(offline_env())
    assert not ok and "not found" in reason


def test_render_is_unavailable_when_rendering_is_turned_off(tmp_path):
    fake = tmp_path / "FL64.exe"
    fake.write_bytes(b"")
    ok, reason = render_fl.availability(
        offline_env(fl_executable=fake, render_enabled=False)
    )
    assert not ok
    assert "turned off" in reason


def test_discovery_reasons_are_phrases_not_sentences():
    """``availability`` composes "FL Studio not found — {reason}", so a reason
    that itself says "not found" produces "not found: not found" on screen."""
    from prosody_core.env import find_fl_executable

    _, reason = find_fl_executable()
    assert "not found" not in reason.lower()


def test_the_composed_render_reason_reads_cleanly():
    _, reason = render_fl.availability(offline_env())
    assert reason.lower().count("not found") == 1


def test_render_returns_a_failed_result_rather_than_raising(tmp_path):
    result = render_fl.render_project(tmp_path / "x.flp", tmp_path, env=offline_env())
    assert result.ok is False
    assert result.message


def test_midi_export_switch_is_refused_not_guessed(tmp_path):
    result = render_fl.export_midi(tmp_path / "x.flp", tmp_path)
    assert not result.ok
    assert "not been confirmed" in result.message


def test_expected_duration_maths():
    assert render_fl.expected_duration_seconds(80, 120.0) == pytest.approx(160.0)
    assert render_fl.expected_duration_seconds(4, 0) == 0.0


def test_render_result_log_is_serialisable():
    result = render_fl.RenderResult(ok=False, message="x")
    assert set(result.as_log()) >= {"command", "exit_code", "seconds", "outputs"}


# -- Test Connection --------------------------------------------------------- #

def test_the_bundled_connection_test_project_ships_and_parses():
    """Settings -> Test Connection renders this; it must be in the package."""
    from prosody_core.extract.render_fl import connection_test_project
    from prosody_core.parse.pyflp_backend import PyFLPBackend

    project = connection_test_project()
    assert project is not None and project.is_file()
    parsed = PyFLPBackend().parse(project)
    assert parsed.tempo == 120.0
    assert parsed.note_count > 0


def test_the_connection_test_asset_is_small():
    """It is shipped in every release; it should stay a probe, not a project."""
    from prosody_core.extract.render_fl import connection_test_project

    assert connection_test_project().stat().st_size < 16 * 1024


def test_test_connection_reports_a_missing_fl_studio():
    result = render_fl.test_connection(offline_env())
    assert not result.ok
    assert "not found" in result.detail


def test_test_connection_does_not_require_rendering_to_be_enabled(tmp_path):
    """The button must work before the user flips the Rendering switch."""
    fake = tmp_path / "FL64.exe"
    fake.write_text("")
    result = render_fl.test_connection(
        offline_env(fl_executable=fake, render_enabled=False), timeout=1
    )
    # It gets past the availability gate and actually tries; failure is about
    # the fake executable, not about the flag being off.
    assert not result.ok
    assert "turned off" not in result.detail


def test_an_unlaunchable_fl_path_fails_cleanly(tmp_path):
    """A path that exists but cannot be executed must not raise."""
    fake = tmp_path / "FL64.exe"
    fake.write_text("not a program")
    result = render_fl.render_project(
        tmp_path / "x.flp", tmp_path / "out",
        env=offline_env(fl_executable=fake, render_enabled=True), timeout=5,
    )
    assert result.ok is False
    assert "could not start FL Studio" in result.message


def test_test_connection_never_touches_the_bundled_asset(tmp_path):
    from prosody_core.extract.render_fl import connection_test_project
    from prosody_core.fs.safety import sha256_file

    asset = connection_test_project()
    before = sha256_file(asset)
    fake = tmp_path / "FL64.exe"
    fake.write_text("")
    render_fl.test_connection(offline_env(fl_executable=fake, render_enabled=True),
                              timeout=1)
    assert sha256_file(asset) == before

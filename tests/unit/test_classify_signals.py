"""Multi-signal role classification.

These check behaviour the product depends on, not exact confidence numbers -
tuning thresholds against synthetic fixtures is exactly the trap ADR-0003 warns
about. What must hold: the right role wins, uncertainty is reported honestly,
and one misleading signal cannot override several agreeing ones.
"""

import pytest

from flpfinisher.classify.signals import (
    analyse_project,
    classify_project,
    measure,
    roles_present,
)
from flpfinisher.health.check import classify_state
from flpfinisher.model.roles import Role
from flpfinisher.model.schemas import ChannelKind, Note, ProjectState
from flpfinisher.parse.pyflp_backend import PyFLPBackend
from tests.fixtures.flp_builder import TYPE_NATIVE, ChannelSpec, NoteSpec, PatternSpec
from tests.fixtures.projects import PPQ, full_kit


@pytest.fixture
def kit(make_flp):
    return PyFLPBackend().parse(make_flp(full_kit()))


# -- feature measurement ---------------------------------------------------- #

def note(pos, length, key=60, vel=100, ch=0):
    return Note(channel=ch, position=pos, length=length, key=key, velocity=vel)


def test_measure_of_no_notes_is_empty():
    f = measure([], PPQ, 4)
    assert not f.has_notes
    assert f.pitch_min is None and f.max_simultaneous == 0


def test_measure_detects_polyphony():
    chord = [note(0, PPQ * 4, k) for k in (48, 52, 55)]
    assert measure(chord, PPQ, 4).max_simultaneous == 3


def test_measure_does_not_count_sequential_notes_as_polyphony():
    line = [note(i * PPQ, PPQ, 60 + i) for i in range(4)]
    assert measure(line, PPQ, 4).max_simultaneous == 1


def test_measure_note_density_per_bar():
    hats = [note(i * PPQ // 2, PPQ // 8) for i in range(32)]
    f = measure(hats, PPQ, 4)
    assert f.notes_per_bar == pytest.approx(8.0, abs=0.6)


def test_measure_on_beat_ratio():
    on = [note(i * PPQ, PPQ // 4) for i in range(8)]
    assert measure(on, PPQ, 4).on_beat_ratio == 1.0
    off = [note(i * PPQ + PPQ // 3, PPQ // 4) for i in range(8)]
    assert measure(off, PPQ, 4).on_beat_ratio == 0.0


def test_measure_counts_distinct_pitches():
    assert measure([note(i * PPQ, 48, 60) for i in range(8)], PPQ, 4).distinct_pitches == 1


# -- classification --------------------------------------------------------- #

EXPECTED = {
    0: Role.KICK, 1: Role.SNARE, 2: Role.HATS,
    3: Role.BASS, 4: Role.CHORDS, 5: Role.MELODY,
}


@pytest.mark.parametrize(("channel", "role"), sorted(EXPECTED.items()))
def test_full_kit_channels_get_the_right_role(kit, channel, role):
    assignments = {a.channel: a for a in classify_project(kit)}
    assert assignments[channel].role is role


def test_classification_reports_which_signals_voted(kit):
    for assignment in classify_project(kit):
        assert assignment.sources, f"channel {assignment.channel} cited no signal"


def test_a_chord_pattern_beats_a_misleading_name(make_flp):
    """Name says kick; the music says three-note sustained chords."""
    spec = full_kit()
    spec.channels = [ChannelSpec("Kick", 1, kind=TYPE_NATIVE)]
    spec.patterns = [
        PatternSpec(1, "P", tuple(
            NoteSpec(b * PPQ * 4, PPQ * 4, k, 90, 0)
            for b in range(4) for k in (48, 52, 55)))
    ]
    project = PyFLPBackend().parse(make_flp(spec))
    result = classify_project(project)[0]
    # The musical evidence must at least contest the name.
    assert result.role is Role.CHORDS or result.confidence < 0.7


def test_an_unnamed_channel_is_not_confidently_classified(make_flp):
    spec = full_kit()
    spec.channels = [ChannelSpec("Pattern 3", 1, kind=TYPE_NATIVE)]
    spec.patterns = [PatternSpec(1, "Pattern 3", (NoteSpec(0, PPQ, 60, 90, 0),))]
    project = PyFLPBackend().parse(make_flp(spec))
    assert not classify_project(project)[0].is_confident


def test_automation_channels_are_never_given_a_musical_role():
    from flpfinisher.classify.signals import classify_channel
    from flpfinisher.model.schemas import Channel

    channel = Channel(index=0, name="Volume", kind=ChannelKind.AUTOMATION)
    result = classify_channel(channel, [], ppq=PPQ, beats_per_bar=4)
    assert result.role is Role.UNKNOWN
    assert result.confidence == 0.0


def test_confidence_never_reaches_certainty(kit):
    assert all(a.confidence <= 0.97 for a in classify_project(kit))


def test_classification_is_deterministic(kit):
    first = classify_project(kit)
    second = classify_project(kit)
    assert first == second


# -- analysis --------------------------------------------------------------- #

def test_analysis_identifies_the_core_kit(kit):
    analysis = analyse_project(kit, classify_state(kit))
    present = roles_present(analysis)
    for role in (Role.KICK, Role.SNARE, Role.HATS, Role.CHORDS, Role.MELODY):
        assert role in present, f"{role.value} not confidently identified"


def test_completion_estimate_is_within_range(kit):
    analysis = analyse_project(kit, ProjectState.LOOP)
    assert 0.0 <= analysis.completion_estimate <= 1.0


def test_roles_present_excludes_unconfident_channels(kit):
    analysis = analyse_project(kit, ProjectState.LOOP)
    for role, channels in roles_present(analysis).items():
        assert role is not Role.UNKNOWN
        assert channels

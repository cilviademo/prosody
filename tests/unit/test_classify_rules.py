"""Tier-1 name hinting. Its job is to be useful without ever being trusted."""

import pytest
from fixtures.flp_builder import ChannelSpec, one_pattern_loop

from prosody_core.classify.rules import analyse, hint_roles, role_from_name
from prosody_core.model.roles import Role
from prosody_core.model.schemas import CONFIDENCE_THRESHOLD, ClassificationMethod, ProjectState
from prosody_core.parse.pyflp_backend import PyFLPBackend


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("Kick", Role.KICK),
        ("kick 01", Role.KICK),
        ("HiHat", Role.HATS),
        ("Open Hat", Role.HATS),
        ("808", Role.BASS),
        ("Sub", Role.BASS),
        ("Rhodes Chords", Role.CHORDS),
        ("Pad Warm", Role.CHORDS),
        ("Lead Synth", Role.MELODY),
        ("Vox Chop", Role.VOCAL),
        ("Riser", Role.FX),
    ],
)
def test_recognisable_names(name, role):
    assert role_from_name(name)[0] is role


@pytest.mark.parametrize("name", ["Pattern 4", "Insert 3", "Channel 1", "Untitled", "Audio 12"])
def test_placeholder_names_produce_no_guess_at_all(name):
    role, confidence, sources = role_from_name(name)
    assert role is Role.UNKNOWN
    assert confidence == 0.0
    assert sources == ()


@pytest.mark.parametrize("name", ["asdf", "sadness", "bdsm", "zzz", ""])
def test_short_hints_do_not_match_inside_unrelated_words(name):
    """'sd' must not match 'asdf'; 'bd' must not match 'bdsm'."""
    assert role_from_name(name)[0] is Role.UNKNOWN


def test_short_hints_still_match_as_whole_words():
    assert role_from_name("BD 1")[0] is Role.KICK
    assert role_from_name("sd_hit")[0] is Role.SNARE
    assert role_from_name("hh closed")[0] is Role.HATS


def test_no_name_only_guess_ever_reaches_the_confidence_threshold():
    """Nothing here may be treated as fact; Phase 5 earns that right."""
    names = ["Kick", "Snare", "HiHat", "808 Bass", "Rhodes Chords", "Lead"]
    for name in names:
        assert role_from_name(name)[1] < CONFIDENCE_THRESHOLD


def test_none_is_handled():
    assert role_from_name(None)[0] is Role.UNKNOWN


def test_hint_roles_covers_every_channel_including_unknowns(make_flp):
    spec = one_pattern_loop()
    spec.channels = [
        ChannelSpec(name="Kick"),
        ChannelSpec(name="Pattern 9"),
        ChannelSpec(name="Rhodes Chords"),
    ]
    project = PyFLPBackend().parse(make_flp(spec))
    roles = hint_roles(project)
    assert len(roles) == 3
    assert [r.channel for r in roles] == [0, 1, 2]
    assert roles[1].role is Role.UNKNOWN
    assert all(r.method is ClassificationMethod.RULES for r in roles)


def test_analysis_reports_no_confident_roles_from_names_alone(make_flp):
    project = PyFLPBackend().parse(make_flp(one_pattern_loop()))
    analysis = analyse(project, ProjectState.LOOP)
    assert analysis.project_id == project.id
    assert analysis.state is ProjectState.LOOP
    assert analysis.confident_roles == ()

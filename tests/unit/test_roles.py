import pytest

from prosody_core.model.roles import DRUM_ROLES, PITCHED_ROLES, Role, normalise_role


def test_vocabulary_is_closed():
    assert {r.value for r in Role} == {
        "chords", "melody", "counter", "bass", "kick", "snare",
        "hats", "perc", "fx", "vocal", "unknown",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("chords", Role.CHORDS),
        ("CHORDS", Role.CHORDS),
        ("hi_hat", Role.HATS),
        ("Hi-Hat", Role.HATS),
        ("open hat", Role.HATS),
        ("808", Role.BASS),
        ("sub_bass", Role.BASS),
        ("pad", Role.CHORDS),
        ("counter_melody", Role.COUNTER),
        ("arp", Role.MELODY),
        ("clap", Role.SNARE),
        ("texture", Role.FX),
    ],
)
def test_extended_vocabulary_normalises_onto_closed_set(raw, expected):
    assert normalise_role(raw) is expected


def test_unrecognised_input_is_unknown_not_an_error():
    assert normalise_role("qwertyuiop") is Role.UNKNOWN
    assert normalise_role("") is Role.UNKNOWN


def test_role_groups_are_disjoint_and_within_vocabulary():
    assert DRUM_ROLES.isdisjoint(PITCHED_ROLES)
    assert set(Role) >= DRUM_ROLES | PITCHED_ROLES

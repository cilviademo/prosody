"""Every shipped genre profile must validate against the schema."""

import pytest

from flpfinisher.arrange import profiles
from flpfinisher.model.roles import Role
from flpfinisher.model.schemas import GenreProfile, SectionType


def test_v1_ships_hiphop_and_rnb():
    assert profiles.available() == ["hiphop", "rnb"]


@pytest.mark.parametrize("genre", profiles.available())
def test_profile_loads_and_validates(genre):
    assert isinstance(profiles.load(genre), GenreProfile)


@pytest.mark.parametrize("genre", profiles.available())
def test_profile_uses_only_the_closed_role_vocabulary(genre):
    profile = profiles.load(genre)
    assert set(profile.role_weights) <= set(Role)


@pytest.mark.parametrize("genre", profiles.available())
def test_profile_energy_keys_are_known_section_types(genre):
    assert set(profiles.load(genre).energy) <= set(SectionType)


@pytest.mark.parametrize("genre", profiles.available())
def test_every_structure_preset_is_present(genre):
    assert set(profiles.load(genre).grammar) == {"short", "balanced", "full"}


@pytest.mark.parametrize("genre", profiles.available())
def test_grammar_entries_are_section_colon_bars(genre):
    for preset, sections in profiles.load(genre).grammar.items():
        for entry in sections:
            name, _, bars = entry.partition(":")
            assert SectionType(name), f"{genre}/{preset}: {entry}"
            assert bars.isdigit() and int(bars) > 0, f"{genre}/{preset}: {entry}"


def test_unknown_genre_raises_with_a_helpful_message():
    with pytest.raises(FileNotFoundError, match="available: hiphop, rnb"):
        profiles.load("polka")

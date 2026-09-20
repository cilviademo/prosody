"""Energy engine, planner and permission enforcement."""

import pytest

from prosody_core.arrange import profiles
from prosody_core.arrange.energy import active_roles, dropout_bars
from prosody_core.arrange.permissions import (
    PermissionDenied,
    assert_allowed,
    assert_plan_allowed,
    describe,
    is_allowed,
)
from prosody_core.arrange.planner import (
    PlanningError,
    build_plan,
    build_variants,
    parse_grammar,
    pattern_roles,
)
from prosody_core.classify.signals import analyse_project
from prosody_core.health.check import classify_state
from prosody_core.model.roles import Role
from prosody_core.model.schemas import PermissionLevel, PlaylistOp, SectionType
from prosody_core.parse.pyflp_backend import PyFLPBackend
from tests.fixtures.projects import full_kit, melody_only, no_notes

ALL = {Role.KICK, Role.SNARE, Role.HATS, Role.BASS, Role.CHORDS, Role.MELODY}


@pytest.fixture
def kit(make_flp):
    project = PyFLPBackend().parse(make_flp(full_kit()))
    return project, analyse_project(project, classify_state(project))


# -- energy ----------------------------------------------------------------- #

def test_higher_energy_activates_more_roles():
    profile = profiles.load("hiphop")
    quiet = active_roles(profile, SectionType.INTRO, 0.2, ALL)
    loud = active_roles(profile, SectionType.HOOK, 0.95, ALL)
    assert len(loud) > len(quiet)


def test_roles_the_project_does_not_have_are_never_activated():
    """The engine must not invent instruments (SPEC section 7)."""
    profile = profiles.load("hiphop")
    available = {Role.CHORDS, Role.MELODY}
    for section in SectionType:
        chosen = active_roles(profile, section, 1.0, available)
        assert set(chosen) <= available


def test_a_section_with_energy_is_never_silent():
    profile = profiles.load("rnb")
    assert active_roles(profile, SectionType.INTRO, 0.05, {Role.CHORDS})


def test_zero_energy_with_no_material_yields_nothing():
    assert active_roles(profiles.load("pop"), SectionType.OUTRO, 0.0, set()) == ()


def test_entry_rules_hold_bass_out_of_the_intro():
    profile = profiles.load("hiphop")
    first = {SectionType.INTRO: 0, SectionType.HOOK: 1}
    chosen = active_roles(profile, SectionType.INTRO, 1.0, ALL,
                          section_index=0, first_index=first)
    assert Role.BASS not in chosen


def test_entry_rules_admit_bass_from_the_first_hook():
    profile = profiles.load("hiphop")
    first = {SectionType.INTRO: 0, SectionType.HOOK: 1}
    chosen = active_roles(profile, SectionType.HOOK, 0.9, ALL,
                          section_index=1, first_index=first)
    assert Role.BASS in chosen


def test_edm_removes_the_kick_from_the_breakdown():
    profile = profiles.load("edm")
    chosen = active_roles(profile, SectionType.BREAKDOWN, 0.9, ALL,
                          section_index=3,
                          first_index={SectionType.DROP: 2, SectionType.BREAKDOWN: 3})
    assert Role.KICK not in chosen


def test_dropout_only_before_the_sections_the_genre_names():
    profile = profiles.load("hiphop")
    assert dropout_bars(profile, SectionType.HOOK, 16) == 1
    assert dropout_bars(profile, SectionType.VERSE, 16) == 0
    assert dropout_bars(profile, None, 16) == 0


def test_short_sections_get_no_dropout():
    assert dropout_bars(profiles.load("hiphop"), SectionType.HOOK, 2) == 0


# -- pattern roles ---------------------------------------------------------- #

def test_each_pattern_gets_a_primary_role(kit):
    project, analysis = kit
    roles = {p.name: p.role for p in pattern_roles(project, analysis)}
    assert roles["Kick"] is Role.KICK
    assert roles["Chords"] is Role.CHORDS
    assert roles["Melody"] is Role.MELODY


def test_empty_patterns_are_skipped(make_flp):
    project = PyFLPBackend().parse(make_flp(no_notes()))
    analysis = analyse_project(project, classify_state(project))
    assert pattern_roles(project, analysis) == ()


# -- grammar ---------------------------------------------------------------- #

def test_parse_grammar():
    assert parse_grammar(("intro:4", "hook:8")) == [
        (SectionType.INTRO, 4), (SectionType.HOOK, 8),
    ]


# -- planner ---------------------------------------------------------------- #

def test_hiphop_balanced_matches_the_specified_structure(kit):
    project, analysis = kit
    plan = build_plan(project, analysis, profiles.load("hiphop"))
    shape = [(s.name.value, s.bars) for s in plan.sections]
    assert shape == [
        ("intro", 4), ("hook", 8), ("verse", 16), ("hook", 8),
        ("verse", 16), ("bridge", 8), ("hook", 16), ("outro", 4),
    ]
    assert plan.total_bars == 80


def test_rnb_balanced_structure(kit):
    project, analysis = kit
    plan = build_plan(project, analysis, profiles.load("rnb"))
    assert [s.name.value for s in plan.sections] == [
        "intro", "verse", "pre", "chorus", "verse", "pre",
        "chorus", "bridge", "chorus", "outro",
    ]


@pytest.mark.parametrize("genre", profiles.available())
@pytest.mark.parametrize("structure", ["short", "balanced", "full"])
def test_every_genre_and_structure_produces_a_valid_plan(kit, genre, structure):
    project, analysis = kit
    plan = build_plan(project, analysis, profiles.load(genre), structure=structure)
    assert plan.total_bars > 0
    assert plan.sections
    assert plan.ops


def test_sections_are_contiguous_and_cover_the_plan(kit):
    project, analysis = kit
    plan = build_plan(project, analysis, profiles.load("pop"))
    assert sum(s.bars for s in plan.sections) == plan.total_bars
    cursor = 1
    for section in plan.sections:
        assert section.start_bar == cursor
        cursor += section.bars


def test_planning_is_deterministic(kit):
    project, analysis = kit
    a = build_plan(project, analysis, profiles.load("trap"), seed=7)
    b = build_plan(project, analysis, profiles.load("trap"), seed=7)
    assert a == b


def test_variants_differ_but_keep_the_same_grammar(kit):
    project, analysis = kit
    variants = build_variants(project, analysis, profiles.load("hiphop"), count=3)
    assert [v.variant for v in variants] == ["A", "B", "C"]
    shapes = {tuple((s.name, s.bars) for s in v.sections) for v in variants}
    assert len(shapes) == 1, "variants must not change the song's shape"


def test_level_zero_plans_contain_only_structural_operations(kit):
    project, analysis = kit
    plan = build_plan(project, analysis, profiles.load("hiphop"))
    assert {op.op for op in plan.ops} <= {"tile", "marker"}


def test_a_project_with_no_notes_cannot_be_arranged(make_flp):
    project = PyFLPBackend().parse(make_flp(no_notes()))
    analysis = analyse_project(project, classify_state(project))
    with pytest.raises(PlanningError, match="nothing to"):
        build_plan(project, analysis, profiles.load("hiphop"))


def test_a_project_with_only_chords_arranges_without_inventing_drums(make_flp):
    project = PyFLPBackend().parse(make_flp(melody_only()))
    analysis = analyse_project(project, classify_state(project))
    plan = build_plan(project, analysis, profiles.load("rnb"))
    for section in plan.sections:
        assert Role.KICK not in section.active_roles
        assert Role.SNARE not in section.active_roles


def test_plan_records_what_it_did(kit):
    project, analysis = kit
    plan = build_plan(project, analysis, profiles.load("hiphop"))
    assert plan.llm_notes and "source patterns" in plan.llm_notes


def test_plan_carries_the_source_project_id(kit):
    project, analysis = kit
    plan = build_plan(project, analysis, profiles.load("edm"))
    assert plan.source_project_id == project.id


# -- permissions ------------------------------------------------------------ #

def test_level_zero_allows_only_structural_ops():
    for op in ("tile", "place", "mute", "duplicate_pattern", "dropout", "marker"):
        assert is_allowed(op, PermissionLevel.STRUCTURE_ONLY)
    for op in ("remove_notes", "generate_counter_melody"):
        assert not is_allowed(op, PermissionLevel.STRUCTURE_ONLY)


def test_assert_allowed_names_the_level_in_its_message():
    with pytest.raises(PermissionDenied, match="Preserve Composition"):
        assert_allowed("remove_notes", PermissionLevel.STRUCTURE_ONLY)


def test_a_plan_mutated_after_validation_is_still_refused(kit):
    """The second gate: the model validator is not the only thing protecting notes."""
    project, analysis = kit
    plan = build_plan(project, analysis, profiles.load("hiphop"))
    smuggled = plan.model_copy(
        update={"ops": (*plan.ops, PlaylistOp(op="remove_notes"))}
    )
    with pytest.raises(PermissionDenied):
        assert_plan_allowed(smuggled)


def test_a_valid_plan_passes_the_second_gate(kit):
    project, analysis = kit
    assert_plan_allowed(build_plan(project, analysis, profiles.load("rnb")))


def test_describe_covers_every_level():
    for level in PermissionLevel:
        assert describe(level)

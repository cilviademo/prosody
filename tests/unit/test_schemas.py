"""The data contract, including the machine-enforced permission levels."""

import pytest
from pydantic import ValidationError

from prosody_core.model.roles import Role
from prosody_core.model.schemas import (
    CONFIDENCE_THRESHOLD,
    ArrangementPlan,
    BeatProject,
    Note,
    Pattern,
    PermissionLevel,
    PlaylistClip,
    PlaylistOp,
    RoleAssignment,
    Section,
    SectionType,
)

DIGEST = "a" * 64


def project(**kw) -> BeatProject:
    return BeatProject(id=DIGEST, source_path="x.flp", backend="test", **kw)


def test_bar_and_duration_maths():
    p = project(tempo=120.0, ppq=96, length_ticks=96 * 4 * 8)
    assert p.length_bars == 8.0
    assert p.duration_seconds == pytest.approx(16.0)


def test_duration_is_none_when_tempo_unknown():
    assert project(length_ticks=384).duration_seconds is None


def test_bar_maths_respects_time_signature():
    p = project(ppq=96, time_signature=(7, 4), length_ticks=96 * 7 * 2)
    assert p.length_bars == 2.0


def test_note_count_sums_patterns():
    notes = tuple(Note(channel=0, position=i * 96, length=48, key=60, velocity=100)
                  for i in range(4))
    p = project(patterns=(Pattern(index=1, notes=notes),
                          Pattern(index=2, notes=notes[:2])))
    assert p.note_count == 6


def test_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        project(nonsense=1)


def test_playlist_clip_requires_a_target_matching_its_kind():
    with pytest.raises(ValidationError):
        PlaylistClip(track=0, kind="pattern")
    with pytest.raises(ValidationError):
        PlaylistClip(track=0, kind="channel", pattern=1)
    assert PlaylistClip(track=0, kind="channel", channel=3).channel == 3


# -- permission enforcement ------------------------------------------------- #

def plan(level: PermissionLevel, ops: tuple[PlaylistOp, ...]) -> ArrangementPlan:
    return ArrangementPlan(
        genre="rnb", source_project_id=DIGEST, tempo=140.0, total_bars=8,
        level=level, ops=ops,
    )


def test_level_zero_allows_structural_ops():
    p = plan(PermissionLevel.STRUCTURE_ONLY,
             (PlaylistOp(op="tile", role=Role.CHORDS, pattern=1, start_bar=1, bars=4),))
    assert p.level is PermissionLevel.STRUCTURE_ONLY


@pytest.mark.parametrize("op", ["remove_notes", "scale_velocity", "generate_counter_melody"])
def test_level_zero_refuses_anything_that_edits_notes(op):
    with pytest.raises(ValidationError, match="exceed permission level 0"):
        plan(PermissionLevel.STRUCTURE_ONLY, (PlaylistOp(op=op),))


def test_level_one_allows_note_removal_but_not_generation():
    plan(PermissionLevel.CONSERVATIVE, (PlaylistOp(op="remove_notes"),))
    with pytest.raises(ValidationError, match="exceed permission level 1"):
        plan(PermissionLevel.CONSERVATIVE, (PlaylistOp(op="generate_counter_melody"),))


def test_level_two_allows_generation():
    plan(PermissionLevel.PRODUCER_ASSIST, (PlaylistOp(op="generate_counter_melody"),))


def test_default_permission_level_is_zero():
    assert ArrangementPlan(
        genre="hiphop", source_project_id=DIGEST, tempo=90.0, total_bars=4
    ).level is PermissionLevel.STRUCTURE_ONLY


def test_unknown_operation_names_are_refused_at_every_level():
    for level in PermissionLevel:
        with pytest.raises(ValidationError):
            plan(level, (PlaylistOp(op="delete_everything"),))


# -- section contiguity ----------------------------------------------------- #

def sections(*spec: tuple[SectionType, int, int]) -> tuple[Section, ...]:
    return tuple(
        Section(name=n, start_bar=s, bars=b, energy=0.5) for n, s, b in spec
    )


def test_contiguous_sections_validate():
    ArrangementPlan(
        genre="rnb", source_project_id=DIGEST, tempo=140.0, total_bars=12,
        sections=sections((SectionType.INTRO, 1, 4), (SectionType.VERSE, 5, 8)),
    )


def test_a_gap_between_sections_is_refused():
    with pytest.raises(ValidationError, match="expected 5"):
        ArrangementPlan(
            genre="rnb", source_project_id=DIGEST, tempo=140.0, total_bars=12,
            sections=sections((SectionType.INTRO, 1, 4), (SectionType.VERSE, 9, 8)),
        )


def test_overlapping_sections_are_refused():
    with pytest.raises(ValidationError):
        ArrangementPlan(
            genre="rnb", source_project_id=DIGEST, tempo=140.0, total_bars=12,
            sections=sections((SectionType.INTRO, 1, 4), (SectionType.VERSE, 3, 8)),
        )


# -- confidence ------------------------------------------------------------- #

def test_low_confidence_is_never_treated_as_fact():
    assert not RoleAssignment(channel=0, role=Role.KICK, confidence=0.69).is_confident
    assert RoleAssignment(channel=0, role=Role.KICK, confidence=0.70).is_confident
    assert CONFIDENCE_THRESHOLD == 0.70

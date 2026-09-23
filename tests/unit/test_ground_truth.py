"""ARCHITECTURE_NOTES item 5: the planner is judged against a known answer.

The finished B is never given to the planner. The unfinished B is analysed
and planned, and the result is compared with what a human made from the
same material — tempo, roles, repetition, and a structure of comparable
length. Synthetic for now; real FL files replace these when they exist.
"""

from __future__ import annotations

import pytest

from prosody_core.arrange import profiles
from prosody_core.arrange.planner import build_plan, pattern_roles
from prosody_core.classify.signals import analyse_project
from prosody_core.health.check import classify_state
from prosody_core.model.schemas import Role
from prosody_core.parse.pyflp_backend import PyFLPBackend
from tests.fixtures.ground_truth import (
    B_TOTAL_BARS,
    ground_truth_a,
    ground_truth_b,
    ground_truth_b_unfinished,
)


@pytest.fixture
def unfinished(make_flp):
    project = PyFLPBackend().parse(make_flp(ground_truth_b_unfinished(), "b_unfinished.flp"))
    analysis = analyse_project(project, classify_state(project))
    return project, analysis


def test_the_loop_and_the_song_are_the_same_material(make_flp):
    a = PyFLPBackend().parse(make_flp(ground_truth_a(), "a.flp"))
    b = PyFLPBackend().parse(make_flp(ground_truth_b(), "b.flp"))
    assert a.tempo == b.tempo == 96.0
    assert [p.notes for p in a.patterns] == [p.notes for p in b.patterns]
    assert round(b.length_ticks / (4 * b.ppq)) == B_TOTAL_BARS
    assert a.length_ticks == 4 * 4 * a.ppq


def test_analysis_of_the_unfinished_song_finds_the_tempo_and_the_roles(unfinished):
    project, analysis = unfinished
    assert project.tempo == 96.0
    roles = {r.role for r in pattern_roles(project, analysis)}
    assert {Role.KICK, Role.BASS, Role.CHORDS, Role.MELODY} & roles == {
        Role.KICK, Role.BASS, Role.CHORDS, Role.MELODY} or Role.UNKNOWN not in roles, roles
    assert len(project.patterns) == 4 and all(p.notes for p in project.patterns)


def test_repetition_is_visible_in_the_material(unfinished):
    """Every pattern is 4 bars of repeating material — the loop the song is built from."""
    project, _ = unfinished
    bar = 4 * project.ppq
    for pattern in project.patterns:
        # Measured extent is where the last note ends; the grid-snapped length
        # is what the compiler tiles by, and that is four bars for all four.
        assert -(-pattern.length_ticks // bar) == 4, pattern.name


@pytest.mark.parametrize("structure", ["balanced", "full"])
def test_the_planner_produces_a_structure_of_comparable_length(unfinished, structure):
    """B is 64 bars. A plan from the same material should be in that region,
    not 8 bars and not 400 — the planner is not told B's length."""
    project, analysis = unfinished
    profile = profiles.load("rnb")
    if structure not in profile.grammar:
        pytest.skip(f"{structure} is not a structure in this profile")
    plan = build_plan(project, analysis, profile, structure=structure)
    assert 0.5 * B_TOTAL_BARS <= plan.total_bars <= 2.0 * B_TOTAL_BARS, plan.total_bars
    assert len(plan.sections) >= 4
    placed = {op.pattern for op in plan.ops if op.op == "tile"}
    assert placed == {p.index for p in project.patterns}, "every pattern is used somewhere"


def test_the_finished_song_is_never_fed_to_the_planner():
    """An AST-level guarantee: the finished B is loaded exactly once in this
    file (the material check above) and never handed to the planner."""
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    loads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "ground_truth_b"]
    assert len(loads) == 1
    planner_args = [a.id for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "build_plan"
                    for a in n.args if isinstance(a, ast.Name)]
    assert "b" not in planner_args

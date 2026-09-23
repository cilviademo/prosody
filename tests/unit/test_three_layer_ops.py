"""ARCHITECTURE_NOTES item 3: intent → semantic ops → mutations, and only C touches the file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prosody_core.api import HANDLERS
from prosody_core.arrange import compile as compile_module
from prosody_core.arrange import profiles
from prosody_core.arrange.planner import build_plan
from prosody_core.classify.signals import analyse_project
from prosody_core.health.check import classify_state
from prosody_core.model.schemas import (
    ArrangementPlan,
    MutationKind,
    MutationOp,
    PlaylistOp,
    Section,
)
from prosody_core.parse.pyflp_backend import PyFLPBackend
from prosody_core.workspace import Workspace
from tests.fixtures.projects import full_kit


@pytest.fixture
def planned(make_flp):
    project = PyFLPBackend().parse(make_flp(full_kit()))
    analysis = analyse_project(project, classify_state(project))
    plan = build_plan(project, analysis, profiles.load("rnb"), structure="balanced")
    return project, plan


def test_no_plan_field_can_hold_a_mutation():
    """The AI boundary is structural: a plan simply cannot carry Layer C."""
    for name, field in ArrangementPlan.model_fields.items():
        assert "MutationOp" not in str(field.annotation), name
    assert "MutationOp" not in str(PlaylistOp.model_fields)
    assert "MutationOp" not in str(Section.model_fields)


def test_every_semantic_op_says_why(planned):
    _, plan = planned
    assert plan.ops
    for op in plan.ops:
        assert op.reason, op
        assert op.evidence, op
        assert 0.0 <= op.confidence <= 1.0
        assert op.permission_level is plan.level
        assert op.reversibility == "reversible"
    assert all(s.goal for s in plan.sections)


def test_compilation_is_deterministic(planned):
    project, plan = planned
    once = compile_module.compile_plan(plan, project)
    twice = compile_module.compile_plan(plan, project)
    assert once == twice
    assert all(isinstance(m, MutationOp) for m in once)


def test_a_tile_compiles_to_whole_repetitions_on_the_grid(planned):
    project, plan = planned
    tpb = compile_module.ticks_per_bar(project)
    mutations = compile_module.compile_plan(plan, project)
    placements = [m for m in mutations if m.kind is MutationKind.PLACE_PLAYLIST_INSTANCE]
    assert placements
    for m in placements:
        assert m.start_tick % tpb == 0, "placements snap to bar lines"
        assert (m.end_tick - m.start_tick) % tpb == 0, "lengths are whole bars"
        assert m.from_op is not None and plan.ops[m.from_op].op == "tile"
    markers = [m for m in mutations if m.kind is MutationKind.WRITE_MARKER]
    assert len(markers) == len(plan.sections)
    assert all(m.label for m in markers)


def test_an_omission_removes_the_placements_it_covers(planned):
    project, plan = planned
    tpb = compile_module.ticks_per_bar(project)
    first_tile = next(op for op in plan.ops if op.op == "tile")
    muted = plan.model_copy(update={"ops": (
        *plan.ops,
        PlaylistOp(op="mute", track=first_tile.track, start_bar=first_tile.start_bar,
                   bars=first_tile.bars, reason="test"),
    )})
    before = compile_module.clips_from(compile_module.compile_plan(plan, project))
    after = compile_module.clips_from(compile_module.compile_plan(muted, project))
    span = ((first_tile.start_bar - 1) * tpb, (first_tile.start_bar - 1 + (first_tile.bars or 0)) * tpb)
    assert len(after) < len(before)
    assert not any(
        c[3] == first_tile.track and span[0] <= c[0] and c[0] + c[2] <= span[1] for c in after
    )


def test_the_writer_consumes_layer_c_and_records_a_result(make_flp, tmp_path):
    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    path = make_flp(full_kit())
    result = HANDLERS["build.run"]({"path": str(path), "genre": "rnb", "arrange": True}, workspace)
    ops = json.loads((Path(result["outDir"]) / "data" / "operations.json").read_text(encoding="utf-8"))

    assert ops["operation_set_id"]
    assert ops["layer_a"] and ops["layer_b"] and ops["layer_c"]
    assert all(m["result"] for m in ops["layer_c"]), "every mutation reports what became of it"
    assert all(op["result"] for op in ops["layer_b"]), "every semantic op reports its outcome"
    assert all(m["from_op"] < len(ops["layer_b"]) for m in ops["layer_c"])
    kinds = {m["kind"] for m in ops["layer_c"]}
    assert "PLACE_PLAYLIST_INSTANCE" in kinds and "WRITE_MARKER" in kinds

    # The file the writer produced matches Layer C exactly.
    flp_files = list(Path(result["outDir"]).glob("*.flp"))
    assert flp_files
    written = PyFLPBackend().parse(flp_files[0])
    placed = sum(1 for m in ops["layer_c"] if m["kind"] == "PLACE_PLAYLIST_INSTANCE")
    assert sum(len(a.clips) for a in written.arrangements) == placed

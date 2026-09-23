"""ARCHITECTURE_NOTES items 1 and 2: provenance and lineage on the contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prosody_core.api import HANDLERS
from prosody_core.classify.signals import ANALYSIS_VERSION
from prosody_core.fs.safety import sha256_file
from prosody_core.model.schemas import (
    Analysis,
    ArrangementPlan,
    BeatProject,
    EvidenceStatus,
    KeyGuess,
    Lineage,
    LineageStage,
    PlaylistOp,
    RoleAssignment,
    Section,
    ValidationLevel,
)
from prosody_core.parse.pyflp_backend import PyFLPBackend
from prosody_core.workspace import Workspace
from tests.fixtures.projects import full_kit


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path / "docs", tmp_path / "state")


# --- item 1 ------------------------------------------------------------------------ #

def test_evidence_and_validation_are_two_fields_not_one():
    assert EvidenceStatus is not ValidationLevel
    assert {e.value for e in EvidenceStatus} == {
        "EXTRACTED", "MEASURED", "INFERRED", "GENERATED", "USER_APPROVED", "UNKNOWN"}
    assert {"UNVERIFIED", "STRUCTURALLY_VALIDATED", "SEMANTICALLY_VALIDATED",
            "FL_STUDIO_VALIDATED"} <= {v.value for v in ValidationLevel}


def test_parser_output_is_extracted_and_unverified(make_flp):
    project = PyFLPBackend().parse(make_flp(full_kit()))
    assert project.evidence_status is EvidenceStatus.EXTRACTED
    assert project.validation_status == ValidationLevel.UNVERIFIED


def test_classifier_output_is_inferred_with_its_confidence():
    role = RoleAssignment(pattern=1, role="kick", confidence=0.8)
    assert role.evidence_status is EvidenceStatus.INFERRED
    assert role.confidence == 0.8
    assert KeyGuess(root="C", mode="minor", confidence=0.6).evidence_status is EvidenceStatus.INFERRED
    assert Analysis(project_id="x").evidence_status is EvidenceStatus.INFERRED


def test_planner_output_is_generated_until_a_user_chooses_it(make_flp, workspace):
    assert Section(name="intro", start_bar=1, bars=4, energy=0.2).evidence_status is EvidenceStatus.GENERATED
    assert PlaylistOp(op="tile").evidence_status is EvidenceStatus.GENERATED

    path = make_flp(full_kit())
    plan = HANDLERS["arrange.plan"]({"path": str(path), "genre": "rnb"}, workspace)
    assert plan  # previewed plans are GENERATED; nothing marks them approved
    result = HANDLERS["build.run"]({"path": str(path), "genre": "rnb", "arrange": True}, workspace)
    chosen = json.loads((Path(result["outDir"]) / "data" / "arrangement.json").read_text(encoding="utf-8"))
    assert chosen["evidence_status"] == "USER_APPROVED"
    assert chosen["validation_status"] == "STRUCTURALLY_VALIDATED"
    assert chosen["ops"][0]["evidence_status"] == "GENERATED", "ops stay GENERATED; the choice is the plan"


# --- item 2 ------------------------------------------------------------------------ #

def test_the_operation_set_id_names_the_ops_and_nothing_else():
    base = {"genre": "rnb", "source_project_id": "p", "tempo": 120.0, "total_bars": 8}
    ops = (PlaylistOp(op="tile", pattern=1, track=0, start_bar=1, bars=8),)
    a = ArrangementPlan(variant="A", seed=1, ops=ops, **base)
    b = ArrangementPlan(variant="B", seed=99, ops=ops, **base)
    c = ArrangementPlan(variant="A", seed=1, ops=(PlaylistOp(op="mute", track=0, start_bar=1, bars=8),), **base)
    assert a.operation_set_id == b.operation_set_id
    assert a.operation_set_id != c.operation_set_id
    assert len(a.operation_set_id) == 16


def test_every_artifact_carries_the_parent_it_descends_from(make_flp, workspace):
    path = make_flp(full_kit())
    parent_hash = sha256_file(path)
    result = HANDLERS["build.run"]({"path": str(path), "genre": "rnb", "arrange": True, "midi": True}, workspace)

    build = json.loads((Path(result["outDir"]) / "reports" / "build.json").read_text(encoding="utf-8"))
    assert build["lineage"]["parent_hash"] == parent_hash
    assert build["lineage"]["operation_set_id"]
    assert build["lineage"]["stage"] == "EXPORTED"
    artifacts = [a for s in build["stages"] for a in s["artifacts"]]
    assert artifacts
    for a in artifacts:
        assert a["lineage"]["parent_hash"] == parent_hash, a["label"]
        assert a["lineage"]["parent_project_id"] == build["project_id"], a["label"]

    job = json.loads((Path(result["outDir"]) / "job.json").read_text(encoding="utf-8"))
    assert job["parentHash"] == parent_hash
    assert job["parentProjectId"] == build["project_id"]
    assert job["operationSetId"] == build["lineage"]["operation_set_id"]
    assert all(o["parentHash"] == parent_hash for o in job["outputs"])

    assert sha256_file(path) == parent_hash, "the ORIGINAL is never mutated"


def test_lineage_stages_are_the_only_chain():
    assert [s.value for s in LineageStage] == ["ORIGINAL", "PROPOSED", "USER_WORKING", "EXPORTED"]
    assert Lineage(parent_project_id="p", parent_hash="h").stage is LineageStage.EXPORTED


def test_existing_json_without_the_new_fields_still_validates(make_flp):
    """Every new field defaults, so an older project.json is not orphaned."""
    project = PyFLPBackend().parse(make_flp(full_kit()))
    raw = project.model_dump(mode="json")
    for key in ("evidence_status", "validation_status"):
        raw.pop(key, None)
    restored = BeatProject.model_validate(raw)
    assert restored.evidence_status is EvidenceStatus.EXTRACTED


# --- item 4 ------------------------------------------------------------------------ #

def _pipeline(out_dir: str) -> dict[str, dict]:
    job = json.loads((Path(out_dir) / "job.json").read_text(encoding="utf-8"))
    return {rec["stage"]: rec for rec in job["pipeline"]}


def test_every_build_records_named_stages_with_hashes(make_flp, workspace):
    path = make_flp(full_kit())
    result = HANDLERS["build.run"]({"path": str(path), "genre": "rnb", "arrange": True, "midi": True}, workspace)
    stages = _pipeline(result["outDir"])

    for name in ("INGESTED", "PROJECT_PARSED", "MIDI_ANALYZED", "STRUCTURE_INFERRED",
                 "ASSETS_RESOLVED", "ARRANGEMENT_READY", "OPTIONS_GENERATED",
                 "USER_REVIEWED", "PROJECT_COMPILED", "EXPORT_VALIDATED"):
        assert stages[name]["state"] == "COMPLETED", name
        assert stages[name]["input_hash"] and stages[name]["output_hash"], name
        assert stages[name]["started_at"] and stages[name]["completed_at"], name
        assert stages[name]["configuration_hash"], name
    assert stages["INGESTED"]["input_hash"] == sha256_file(path)
    assert stages["AUDIO_ANALYZED"]["state"] == "SKIPPED"
    assert stages["MIXER_ANALYZED"]["state"] == "SKIPPED"
    assert {s["analysis_version"] for s in stages.values()} == {ANALYSIS_VERSION}


def test_resuming_reuses_stages_whose_inputs_did_not_change(make_flp, workspace):
    path = make_flp(full_kit())
    first = HANDLERS["build.run"]({"path": str(path), "genre": "rnb", "arrange": True, "midi": True}, workspace)
    second = HANDLERS["jobs.resume"]({"outDir": first["outDir"]}, workspace)
    assert second["outDir"] != first["outDir"], "a resume is a new job, the old one stays intact"

    before, after = _pipeline(first["outDir"]), _pipeline(second["outDir"])
    for name in ("PROJECT_PARSED", "MIDI_ANALYZED", "USER_REVIEWED"):
        assert after[name]["state"] == "RESUMED", name
        assert after[name]["output_hash"] == before[name]["output_hash"], name
    assert after["PROJECT_COMPILED"]["state"] == "COMPLETED"
    assert after["EXPORT_VALIDATED"]["state"] == "COMPLETED"


def test_a_changed_configuration_invalidates_the_resume(make_flp, workspace):
    path = make_flp(full_kit())
    first = HANDLERS["build.run"]({"path": str(path), "genre": "rnb", "arrange": True, "midi": True}, workspace)
    payload = {"path": str(path), "genre": "trap", "arrange": True, "midi": True,
               "resumeFrom": first["outDir"]}
    second = HANDLERS["build.run"](payload, workspace)
    after = _pipeline(second["outDir"])
    assert after["USER_REVIEWED"]["state"] == "COMPLETED", "a different genre is a different plan"
    assert after["USER_REVIEWED"]["configuration_hash"] != _pipeline(first["outDir"])["USER_REVIEWED"]["configuration_hash"]

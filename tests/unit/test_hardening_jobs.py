"""HARDENING P0.4: an interrupted build explains itself."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prosody_core import jobs
from prosody_core.api import HANDLERS
from prosody_core.workspace import Workspace
from tests.fixtures.projects import full_kit


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path / "docs", tmp_path / "state")


def test_a_finished_build_writes_a_complete_manifest(workspace, make_flp):
    source = make_flp(full_kit())
    result = HANDLERS["build.run"](
        {"path": str(source), "genre": "rnb", "arrange": True}, workspace
    )
    manifest = json.loads(
        (Path(result["outDir"]) / "job.json").read_text(encoding="utf-8")
    )

    assert manifest["sourcePath"] == str(source)
    assert len(manifest["sourceHash"]) == 64
    assert manifest["operation"] == "arrange"
    assert manifest["options"]["genre"] == "rnb"
    assert manifest["workingCopy"] and "jobs" in manifest["workingCopy"]
    assert manifest["startedAt"] and manifest["finishedAt"]
    assert manifest["stages"], "no stages were recorded"
    assert all(s["at"] for s in manifest["stages"]), "a stage has no timestamp"
    assert manifest["outputs"], "no outputs were recorded"
    assert manifest["validationLevel"] == "STRUCTURALLY_VALIDATED"


def test_a_finished_build_is_not_reported_as_interrupted(workspace, make_flp):
    source = make_flp(full_kit())
    HANDLERS["build.run"]({"path": str(source), "genre": "rnb"}, workspace)
    assert HANDLERS["jobs.interrupted"]({}, workspace)["count"] == 0


def test_a_build_that_dies_midway_is_found_and_described(workspace, make_flp, monkeypatch):
    """The stage it reached is the useful part, not just that it failed."""
    from prosody_core import build as build_module

    source = make_flp(full_kit())

    def die(*_a, **_k):
        raise KeyboardInterrupt("the user closed Prosody")

    # build.py imported the name, so patching the module it came from would
    # miss the reference the build actually calls.
    monkeypatch.setattr(build_module, "write_role_midi", die)
    with pytest.raises(KeyboardInterrupt):
        HANDLERS["build.run"]({"path": str(source), "genre": "rnb", "midi": True}, workspace)

    found = HANDLERS["jobs.interrupted"]({}, workspace)
    assert found["count"] == 1
    entry = found["interrupted"][0]
    assert entry["sourcePath"] == str(source)
    assert entry["sourceExists"] is True
    assert entry["stageCount"] >= 1
    assert entry["lastStage"], "the manifest does not say how far it got"
    assert entry["startedAt"]


def test_an_interrupted_folder_can_be_discarded_by_choice(workspace, make_flp, monkeypatch):
    from prosody_core import build as build_module

    source = make_flp(full_kit())
    monkeypatch.setattr(
        build_module, "write_role_midi",
        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        HANDLERS["build.run"]({"path": str(source), "genre": "rnb", "midi": True}, workspace)

    out_dir = HANDLERS["jobs.interrupted"]({}, workspace)["interrupted"][0]["outDir"]
    HANDLERS["jobs.discard"]({"outDir": out_dir}, workspace)

    assert not Path(out_dir).exists()
    assert HANDLERS["jobs.interrupted"]({}, workspace)["count"] == 0
    assert source.is_file(), "discarding an output touched the source"


def test_discard_refuses_anything_outside_the_export_root(workspace, tmp_path):
    """The one irreversible action here does not take the caller's word."""
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.flp").write_bytes(b"FLhd")

    with pytest.raises(ValueError, match="not inside"):
        jobs.discard(outside, workspace.export_root())
    assert (outside / "keep.flp").is_file()

    with pytest.raises(ValueError, match="export root itself"):
        jobs.discard(workspace.export_root(), workspace.export_root())


def test_a_stray_partial_is_surfaced_even_in_a_finished_folder(workspace, make_flp):
    source = make_flp(full_kit())
    result = HANDLERS["build.run"]({"path": str(source), "genre": "rnb"}, workspace)
    out_dir = Path(result["outDir"])
    (out_dir / "Full.wav.abcd1234.partial").write_bytes(b"half a render")

    found = HANDLERS["jobs.interrupted"]({}, workspace)
    assert found["count"] == 1
    assert "partial" in found["interrupted"][0]["lastStage"]
    assert len(found["interrupted"][0]["partials"]) == 1


def test_clearing_partials_leaves_finished_files_alone(workspace, make_flp):
    source = make_flp(full_kit())
    result = HANDLERS["build.run"]({"path": str(source), "genre": "rnb"}, workspace)
    out_dir = Path(result["outDir"])
    (out_dir / "x.flp.deadbeef.partial").write_bytes(b"half")
    real = sorted(p.name for p in out_dir.rglob("*") if p.is_file() and not p.name.endswith(".partial"))

    removed = HANDLERS["jobs.clearPartials"]({}, workspace)
    assert removed["count"] == 1

    after = sorted(p.name for p in out_dir.rglob("*") if p.is_file())
    assert after == real, "clearing partials removed a finished file"


def test_a_folder_from_before_manifests_existed_is_not_called_interrupted(workspace):
    """An older export with no manifest is not a failure to report."""
    old = workspace.export_root() / "Legacy__PROSODY_RNB_V001"
    (old / "data").mkdir(parents=True)
    (old / "data" / "project.json").write_text("{}", encoding="utf-8")
    assert HANDLERS["jobs.interrupted"]({}, workspace)["count"] == 0


def test_an_unreadable_manifest_is_reported_rather_than_crashing(workspace):
    folder = workspace.export_root() / "Broken__PROSODY_RNB_V001"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text("{not json", encoding="utf-8")

    found = jobs.scan(workspace.export_root())
    assert len(found) == 1
    assert "unreadable" in found[0].last_stage

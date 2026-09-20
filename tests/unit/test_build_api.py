"""The build orchestrator and the desktop API.

These cover the behaviour the product promises most loudly: one failure never
cancels the rest, the original is never touched, and an unavailable capability
is reported rather than faked.
"""

import json

import pytest

from flpfinisher import api as api_module
from flpfinisher.build import BuildOptions, build, output_name, prepare_output_dir
from flpfinisher.fs.safety import sha256_file
from flpfinisher.index import db
from flpfinisher.model.schemas import OutputTier, PermissionLevel, StageStatus
from flpfinisher.workspace import Workspace
from tests.fixtures.projects import full_kit, melody_only, no_notes


@pytest.fixture
def workspace(tmp_path):
    return Workspace.open(tmp_path / "Prosody")


@pytest.fixture
def source(make_flp):
    return make_flp(full_kit(), "Starfall.flp")


def run(source, tmp_path, **kw):
    options = BuildOptions(
        want_wav=False, want_mp3=False, want_stems=False, **kw
    )
    return build(source, export_root=tmp_path / "Exports", options=options)


# -- workspace -------------------------------------------------------------- #

def test_workspace_creates_its_folders(workspace):
    for directory in (workspace.projects, workspace.cache, workspace.exports,
                      workspace.logs, workspace.database):
        assert directory.is_dir()


def test_settings_round_trip(workspace):
    saved = workspace.save_settings({"creativity_level": 2, "ai_provider": "claude"})
    assert saved["creativity_level"] == 2
    assert workspace.load_settings()["ai_provider"] == "claude"


def test_unknown_settings_keys_are_ignored(workspace):
    assert "nonsense" not in workspace.save_settings({"nonsense": 1})


def test_corrupt_settings_fall_back_to_defaults(workspace):
    workspace.settings_path.write_text("{ not json")
    assert workspace.load_settings()["creativity_level"] == 0


# -- database --------------------------------------------------------------- #

def test_migrations_apply_once(workspace):
    assert db.migrate(workspace.db_path) == 1
    assert db.migrate(workspace.db_path) == 1


def test_projects_upsert_rather_than_duplicate(workspace):
    from flpfinisher.model.schemas import LibraryEntry

    db.migrate(workspace.db_path)
    for name in ("First", "Second"):
        db.upsert_project(workspace.db_path, LibraryEntry(
            project_id="a" * 64, name=name, source_path="/x.flp"))
    rows = db.list_projects(workspace.db_path)
    assert len(rows) == 1 and rows[0].name == "Second"


def test_listing_an_absent_database_is_empty(tmp_path):
    assert db.list_projects(tmp_path / "missing.db") == []


def test_forgetting_a_project_removes_only_the_row(workspace):
    from flpfinisher.model.schemas import LibraryEntry

    db.migrate(workspace.db_path)
    db.upsert_project(workspace.db_path, LibraryEntry(
        project_id="b" * 64, name="X", source_path="/x.flp"))
    db.record_build(workspace.db_path, "b" * 64, genre="rnb", structure="balanced",
                    level=0, tier="native", out_dir="/out")
    db.forget_project(workspace.db_path, "b" * 64)
    assert db.list_projects(workspace.db_path) == []


# -- output naming ---------------------------------------------------------- #

def test_output_name_carries_the_product_genre_and_version(tmp_path):
    assert output_name(tmp_path / "Starfall.flp", "rnb") == "Starfall__PROSODY_RNB_V001"
    assert output_name(tmp_path / "Starfall.flp", "rnb", 12) == "Starfall__PROSODY_RNB_V012"


def test_output_directories_are_versioned_never_reused(tmp_path):
    source = tmp_path / "Starfall.flp"
    first = prepare_output_dir(tmp_path / "out", source, "rnb")
    second = prepare_output_dir(tmp_path / "out", source, "rnb")
    assert first.name == "Starfall__PROSODY_RNB_V001"
    assert second.name == "Starfall__PROSODY_RNB_V002"
    assert first != second


def test_generated_files_share_the_versioned_folder_name(source, tmp_path):
    """A .flp moved out of its folder must still say which version it is."""
    from pathlib import Path

    result = run(source, tmp_path, genre="rnb")
    out = Path(result.out_dir)
    assert out.name == "Starfall__PROSODY_RNB_V001"
    assert (out / f"{out.name}.flp").is_file()
    assert (out / f"{out.name}.zip").is_file()


# -- build ------------------------------------------------------------------ #

def test_a_full_build_reaches_the_native_tier(source, tmp_path):
    result = run(source, tmp_path, genre="hiphop")
    assert result.tier is OutputTier.NATIVE
    assert result.flp_path and result.ok


def test_the_source_is_verified_unchanged(source, tmp_path):
    before = sha256_file(source)
    result = run(source, tmp_path, genre="rnb")
    assert result.source_hash_verified
    assert sha256_file(source) == before


def test_every_stage_is_reported(source, tmp_path):
    result = run(source, tmp_path, genre="trap")
    names = [s.name for s in result.stages]
    assert "Preparing project" in names
    assert "Planning arrangement" in names
    assert "Writing FL Studio project" in names


def test_unavailable_rendering_is_skipped_with_a_reason(source, tmp_path):
    options = BuildOptions(want_wav=True, want_mp3=True, want_stems=True)
    result = build(source, export_root=tmp_path / "Exports", options=options)
    render = next(s for s in result.stages if s.name == "Rendering audio")
    assert render.status is StageStatus.SKIPPED
    assert render.detail


def test_skipping_audio_does_not_prevent_the_other_outputs(source, tmp_path):
    options = BuildOptions(want_wav=True, want_mp3=True, want_stems=True)
    result = build(source, export_root=tmp_path / "Exports", options=options)
    kinds = {a.kind.value for a in result.artifacts}
    assert "flp" in kinds and "midi" in kinds and "zip" in kinds


def test_stems_are_never_faked_from_the_master(source, tmp_path):
    options = BuildOptions(want_wav=True, want_stems=True)
    result = build(source, export_root=tmp_path / "Exports", options=options)
    assert not any(a.kind.value == "stem" for a in result.artifacts)


def test_the_expected_files_are_written(source, tmp_path):
    from pathlib import Path

    result = run(source, tmp_path, genre="pop")
    out = Path(result.out_dir)
    for relative in (
        "data/project.json", "data/analysis.json", "data/arrangement.json",
        "reports/health.json", "reports/validation.json", "reports/build.json",
        "reports/operations.log",
    ):
        assert (out / relative).is_file(), relative


def test_written_json_is_valid(source, tmp_path):
    from pathlib import Path

    result = run(source, tmp_path, genre="edm")
    payload = json.loads((Path(result.out_dir) / "data" / "arrangement.json").read_text())
    assert payload["genre"] == "edm"
    assert payload["sections"]


def test_extract_only_skips_arrangement(source, tmp_path):
    result = run(source, tmp_path, arrange=False)
    assert not any(s.name == "Planning arrangement" for s in result.stages)
    assert result.flp_path is None
    assert result.tier is OutputTier.PACK


def test_a_project_that_cannot_be_arranged_falls_back_to_a_pack(make_flp, tmp_path):
    source = make_flp(no_notes(), "Empty.flp")
    result = run(source, tmp_path, genre="hiphop")
    assert result.tier is OutputTier.PACK
    assert "Arrangement Pack" in result.message


def test_the_fallback_is_not_described_as_an_error(make_flp, tmp_path):
    source = make_flp(no_notes(), "Empty.flp")
    result = run(source, tmp_path, genre="hiphop")
    assert "error" not in result.message.lower()
    assert "fail" not in result.message.lower()


def test_a_minimal_project_still_builds(make_flp, tmp_path):
    source = make_flp(melody_only(), "Sketch.flp")
    result = run(source, tmp_path, genre="rnb")
    assert result.tier is OutputTier.NATIVE


def test_progress_is_streamed_in_order(source, tmp_path):
    seen: list[tuple[str, str]] = []
    build(
        source, export_root=tmp_path / "Exports",
        options=BuildOptions(want_wav=False, want_mp3=False),
        progress=lambda stage, status, detail: seen.append((stage, status)),
    )
    assert seen[0][1] == "running"
    running = [s for s, st in seen if st == "running"]
    finished = [s for s, st in seen if st != "running"]
    assert set(running) == set(finished)


def test_level_zero_is_the_default():
    assert BuildOptions().level is PermissionLevel.STRUCTURE_ONLY


# -- API -------------------------------------------------------------------- #

def call(method, payload, workspace):
    """Invoke a handler and capture the emitted envelopes."""
    captured: list[dict] = []
    original = api_module.emit
    api_module.emit = captured.append
    try:
        api_module.dispatch(method, payload, workspace)
    finally:
        api_module.emit = original
    return captured[-1], captured[:-1]


def test_environment_reports_capabilities(workspace):
    result, _ = call("environment", {}, workspace)
    assert result["ok"]
    assert "canRender" in result["data"]
    assert "stemReason" in result["data"]


def test_genres_are_returned_in_display_order(workspace):
    result, _ = call("genres", {}, workspace)
    assert [g["id"] for g in result["data"]["genres"]][:2] == ["hiphop", "rnb"]


def test_inspect_returns_a_project_summary(source, workspace):
    result, _ = call("project.inspect", {"path": str(source)}, workspace)
    assert result["ok"]
    data = result["data"]
    assert data["tempo"] == 142.0
    assert data["counts"]["patterns"] == 6
    assert data["canArrange"]


def test_inspect_exposes_roles_with_a_likely_tier(source, workspace):
    result, _ = call("project.inspect", {"path": str(source)}, workspace)
    roles = result["data"]["roles"]
    assert all({"role", "present", "likely", "label"} <= set(r) for r in roles)


def test_inspect_of_a_missing_file_is_a_clean_error(workspace):
    result, _ = call("project.inspect", {"path": "/nope/x.flp"}, workspace)
    assert not result["ok"]
    assert result["error"] == "invalid_input"


def test_inspect_of_a_non_flp_is_rejected(workspace, tmp_path):
    other = tmp_path / "song.wav"
    other.write_bytes(b"RIFF")
    result, _ = call("project.inspect", {"path": str(other)}, workspace)
    assert not result["ok"]


def test_inspect_of_a_corrupt_flp_reports_parse_failure(workspace, tmp_path):
    bad = tmp_path / "bad.flp"
    bad.write_bytes(b"NOTANFLP")
    result, _ = call("project.inspect", {"path": str(bad)}, workspace)
    assert not result["ok"]
    assert result["error"] == "parse_failed"


def test_plan_returns_sections_and_lanes(source, workspace):
    result, _ = call(
        "arrange.plan",
        {"path": str(source), "genre": "hiphop", "structure": "balanced", "level": 0},
        workspace,
    )
    data = result["data"]
    assert data["totalBars"] == 80
    assert len(data["sections"]) == 8
    assert data["lanes"]


def test_plan_writes_nothing(source, workspace, tmp_path):
    before = set(tmp_path.rglob("*"))
    call("arrange.plan", {"path": str(source), "genre": "rnb"}, workspace)
    assert set(tmp_path.rglob("*")) == before


def test_build_streams_progress_then_a_result(source, workspace, tmp_path):
    result, progress = call(
        "build.run",
        {"path": str(source), "genre": "rnb", "wav": False, "mp3": False,
         "exportRoot": str(tmp_path / "Exports")},
        workspace,
    )
    assert result["ok"]
    assert progress and all(p["event"] == "progress" for p in progress)
    assert result["data"]["tier"] == "native"


def test_build_records_the_project_in_the_library(source, workspace, tmp_path):
    call("build.run",
         {"path": str(source), "genre": "trap", "wav": False, "mp3": False,
          "exportRoot": str(tmp_path / "Exports")}, workspace)
    listing, _ = call("library.list", {}, workspace)
    projects = listing["data"]["projects"]
    assert projects and projects[0]["genre"] == "trap"


def test_unknown_methods_are_reported_not_raised(workspace):
    result, _ = call("nope", {}, workspace)
    assert not result["ok"] and result["error"] == "unknown_method"


def test_settings_round_trip_through_the_api(workspace):
    call("settings.set", {"settings": {"wav_bit_depth": 32}}, workspace)
    result, _ = call("settings.get", {}, workspace)
    assert result["data"]["wav_bit_depth"] == 32


def test_key_detection_returns_a_label_and_confidence(source, workspace):
    result, _ = call("project.inspect", {"path": str(source)}, workspace)
    data = result["data"]
    assert data["key"] is None or isinstance(data["key"], str)
    assert 0.0 <= data["keyConfidence"] <= 1.0


def test_sanitised_llm_payload_contains_no_paths_or_names(source, workspace):
    from flpfinisher.ai.planner import PlanRequest, sanitise
    from flpfinisher.classify.signals import analyse_project
    from flpfinisher.health.check import classify_state
    from flpfinisher.parse.pyflp_backend import PyFLPBackend

    project = PyFLPBackend().parse(source)
    analysis = analyse_project(project, classify_state(project))
    payload = sanitise(PlanRequest(project=project, analysis=analysis, genre="rnb"))
    blob = json.dumps(payload)
    assert "Starfall" not in blob
    assert str(source) not in blob
    assert "Rhodes" not in blob


def test_the_rule_planner_is_always_available():
    from flpfinisher.ai.planner import RuleBasedPlanner

    ok, _ = RuleBasedPlanner().available()
    assert ok


def test_an_llm_provider_falls_back_instead_of_failing(source):
    from flpfinisher.ai.planner import ClaudePlanner, PlanRequest
    from flpfinisher.classify.signals import analyse_project
    from flpfinisher.health.check import classify_state
    from flpfinisher.parse.pyflp_backend import PyFLPBackend

    project = PyFLPBackend().parse(source)
    analysis = analyse_project(project, classify_state(project))
    plans = ClaudePlanner().plan(
        PlanRequest(project=project, analysis=analysis, genre="pop")
    )
    assert plans and plans[0].sections


# -- settings actually take effect ------------------------------------------ #

def test_stored_fl_path_is_used_over_discovery(workspace, tmp_path):
    """The Settings screen saves a path; the environment must honour it."""
    from flpfinisher.env import describe

    fake = tmp_path / "FL64.exe"
    fake.write_bytes(b"")
    env = describe({"fl_executable": str(fake)})
    assert env.fl_executable == fake
    assert "Settings" in env.fl_discovery


def test_a_stored_fl_path_that_no_longer_exists_is_reported(tmp_path):
    from flpfinisher.env import describe

    env = describe({"fl_executable": str(tmp_path / "gone.exe")})
    assert env.fl_executable is None
    assert "does not exist" in env.fl_discovery


def test_the_rendering_toggle_enables_rendering(tmp_path, monkeypatch):
    """Without this wiring the toggle saves a preference nothing reads."""
    from flpfinisher.env import describe

    monkeypatch.delenv("FLPF_RENDER", raising=False)
    assert describe({}).render_enabled is False
    assert describe({"render_enabled": True}).render_enabled is True


def test_the_environment_flag_still_works_for_the_cli(monkeypatch):
    from flpfinisher.env import describe

    monkeypatch.setenv("FLPF_RENDER", "1")
    assert describe({}).render_enabled is True


def test_environment_endpoint_reflects_saved_settings(workspace, tmp_path):
    fake = tmp_path / "FL64.exe"
    fake.write_bytes(b"")
    call("settings.set",
         {"settings": {"fl_executable": str(fake), "render_enabled": True}},
         workspace)
    result, _ = call("environment", {}, workspace)
    assert result["data"]["flExecutable"] == str(fake)
    assert result["data"]["canRender"] is True

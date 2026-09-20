"""HARDENING P0.3 and P0.4: the source is never touched, outputs never tear."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from prosody_core.fs.safety import sha256_file
from prosody_core.fs.source import (
    SourceChanged,
    SourceWouldBeModified,
    assert_not_the_source,
    atomic_write,
    atomic_write_versioned,
    is_same_file,
    open_source,
    stale_partials,
    working_copy,
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "Starfall.flp"
    path.write_bytes(b"FLhd" + b"\x00" * 60)
    return path


# --- P0.3: the destination is never the source ----------------------------- #

def test_writing_over_the_source_is_refused(source, tmp_path):
    with pytest.raises(SourceWouldBeModified):
        atomic_write(source, b"new bytes", source=source)
    assert source.read_bytes().startswith(b"FLhd"), "the source was modified"


def test_a_different_spelling_of_the_source_is_still_the_source(source, tmp_path):
    """Comparing path strings is not enough; compare the file."""
    sneaky = tmp_path / "." / "Starfall.flp"
    with pytest.raises(SourceWouldBeModified):
        atomic_write(sneaky, b"new bytes", source=source)


@pytest.mark.skipif(os.name == "nt", reason="POSIX hard links")
def test_a_hard_link_to_the_source_is_the_source(source, tmp_path):
    """st_dev/st_ino catch what a path comparison cannot."""
    link = tmp_path / "elsewhere.flp"
    os.link(source, link)
    assert is_same_file(link, source)
    with pytest.raises(SourceWouldBeModified):
        atomic_write(link, b"new bytes", source=source)
    assert source.read_bytes().startswith(b"FLhd")


def test_writing_a_different_name_in_the_source_folder_is_allowed(source, tmp_path):
    """The user may legitimately export beside their project."""
    out = atomic_write(source.parent / "Starfall__PROSODY_RNB_V001.flp", b"derived", source=source)
    assert out.read_bytes() == b"derived"
    assert source.read_bytes().startswith(b"FLhd")


def test_a_same_named_file_in_the_source_folder_is_refused(source, tmp_path):
    other = tmp_path / "nested"
    other.mkdir()
    # A different folder with the same filename is fine.
    atomic_write(other / "Starfall.flp", b"ok", source=source)
    # The same folder is not.
    with pytest.raises(SourceWouldBeModified):
        assert_not_the_source(source.parent / "Starfall.flp", source)


# --- P0.3: hash either side ------------------------------------------------ #

def test_a_source_edited_mid_run_is_caught(source):
    with pytest.raises(SourceChanged) as raised, open_source(source):
        source.write_bytes(b"FLhd" + b"\xff" * 60)
    assert "Nothing was written" in str(raised.value)


def test_an_untouched_source_passes(source):
    with open_source(source) as path:
        assert path.read_bytes().startswith(b"FLhd")


def test_a_source_deleted_mid_run_is_caught(source):
    with pytest.raises(SourceChanged), open_source(source):
        source.unlink()


# --- P0.3: copy-on-analyze -------------------------------------------------- #

def test_work_happens_on_a_copy_not_the_original(source, tmp_path):
    copy = working_copy(source, tmp_path / "cache", job_id="abc123")
    assert copy.path != source
    assert copy.path.parent.name == "abc123"
    assert copy.path.read_bytes() == source.read_bytes()
    assert copy.source_hash == sha256_file(source)

    # Destroying the copy leaves the original untouched.
    copy.path.write_bytes(b"ruined")
    assert source.read_bytes().startswith(b"FLhd")


# --- P0.4: transactional outputs -------------------------------------------- #

def test_nothing_partial_survives_a_successful_write(tmp_path):
    atomic_write(tmp_path / "out.flp", b"complete")
    assert (tmp_path / "out.flp").read_bytes() == b"complete"
    assert stale_partials(tmp_path) == []


def test_a_failed_write_leaves_no_partial_and_no_destination(tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        atomic_write(tmp_path / "out.flp", b"never lands")

    assert not (tmp_path / "out.flp").exists()
    assert stale_partials(tmp_path) == [], "a .partial was left behind"


def test_a_previous_version_survives_a_failed_rewrite(tmp_path, monkeypatch):
    """The reason to write a sibling and rename: a crash cannot eat good data."""
    target = tmp_path / "out.flp"
    atomic_write(target, b"version one")

    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        atomic_write(target, b"version two")
    assert target.read_bytes() == b"version one"


def test_a_locked_destination_steps_to_the_next_version(tmp_path, monkeypatch):
    """FL holding the last export open must not fail the build or delete it."""
    (tmp_path / "Track.flp").write_bytes(b"open in FL")

    real_replace = os.replace

    def locked(src, dst, *args, **kwargs):
        if Path(dst).name == "Track.flp":
            raise PermissionError("The process cannot access the file")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", locked)
    written = atomic_write_versioned(tmp_path, "Track", ".flp", b"new take")

    assert written.name == "Track_V002.flp"
    assert written.read_bytes() == b"new take"
    assert (tmp_path / "Track.flp").read_bytes() == b"open in FL", "the locked file was touched"
    assert stale_partials(tmp_path) == []


def test_the_stale_partial_sweep_finds_leftovers(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.flp.deadbeef.partial").write_bytes(b"half")
    (tmp_path / "a" / "x.flp").write_bytes(b"whole")
    assert [p.name for p in stale_partials(tmp_path)] == ["x.flp.deadbeef.partial"]


# --- the guards, in the real build path ------------------------------------- #

def test_a_build_parses_a_copy_and_never_opens_the_original(tmp_path, make_flp, monkeypatch):
    """Copy-on-analyze is only real if the parser never sees the original."""
    from prosody_core.api import HANDLERS
    from prosody_core.parse import pyflp_backend
    from prosody_core.workspace import Workspace
    from tests.fixtures.projects import full_kit

    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    original = make_flp(full_kit())

    parsed: list[Path] = []
    real_parse = pyflp_backend.PyFLPBackend.parse

    def spy(self, path, *args, **kwargs):
        parsed.append(Path(path))
        return real_parse(self, path, *args, **kwargs)

    monkeypatch.setattr(pyflp_backend.PyFLPBackend, "parse", spy)
    result = HANDLERS["build.run"]({"path": str(original), "genre": "rnb", "arrange": True}, workspace)
    assert result.get("outDir")

    assert parsed, "nothing was parsed"
    assert all(p != original for p in parsed), (
        f"the build parsed the user's original directly: {parsed}"
    )
    assert any("jobs" in p.parts for p in parsed), f"no working copy was used: {parsed}"


def test_the_writer_refuses_the_original_before_writing_a_byte(tmp_path, make_flp):
    """The check must run first; a check after the write protects nothing."""
    from prosody_core.arrange import profiles
    from prosody_core.arrange.planner import build_plan
    from prosody_core.classify.signals import analyse_project
    from prosody_core.health.check import classify_state
    from prosody_core.parse.pyflp_backend import PyFLPBackend
    from prosody_core.write.flp_writer import write_arrangement
    from tests.fixtures.projects import full_kit

    original = make_flp(full_kit())
    before = original.read_bytes()

    project = PyFLPBackend().parse(original)
    analysis = analyse_project(project, classify_state(project))
    plan = build_plan(project, analysis, profiles.load("rnb"), structure="balanced")

    with pytest.raises(SourceWouldBeModified):
        write_arrangement(original, original, plan, project)
    assert original.read_bytes() == before, "the source was written to"

    # And with a working copy as the read source, the original is still
    # protected when it is named as the destination.
    copy = working_copy(original, tmp_path / "cache")
    with pytest.raises(SourceWouldBeModified):
        write_arrangement(copy.path, original, plan, project, protect=original)
    assert original.read_bytes() == before


def test_an_export_records_the_users_path_not_the_cache_copy(tmp_path, make_flp):
    """Parsing a copy must not leak the cache path into the export.

    project.json is what a library rebuild reads, and what tells the UI
    whether the source is still on disk. A path under Cache/jobs stops
    existing the moment the cache is cleared.
    """
    import json

    from prosody_core.api import HANDLERS
    from prosody_core.workspace import Workspace
    from tests.fixtures.projects import full_kit

    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    original = make_flp(full_kit())

    result = HANDLERS["build.run"]({"path": str(original), "genre": "rnb"}, workspace)
    recorded = json.loads(
        (Path(result["outDir"]) / "data" / "project.json").read_text(encoding="utf-8")
    )
    assert recorded["source_path"] == str(original)
    assert "jobs" not in recorded["source_path"]

    listed = HANDLERS["library.list"]({}, workspace)["projects"]
    assert [p["path"] for p in listed] == [str(original)]
    assert all(p["exists"] for p in listed)


def test_previewing_a_plan_leaves_nothing_on_disk(tmp_path, make_flp):
    from prosody_core.api import HANDLERS
    from prosody_core.workspace import Workspace
    from tests.fixtures.projects import full_kit

    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    original = make_flp(full_kit())
    before = set(tmp_path.rglob("*"))

    HANDLERS["arrange.plan"]({"path": str(original), "genre": "rnb"}, workspace)
    HANDLERS["project.inspect"]({"path": str(original)}, workspace)

    new = set(tmp_path.rglob("*")) - before
    leftover = [p for p in new if "Cache" in p.parts]
    assert leftover == [], f"a preview left files in the cache: {leftover}"

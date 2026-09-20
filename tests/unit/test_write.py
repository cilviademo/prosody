"""The derivative writer: the part of the product that must never lose work."""

import pytest

from flpfinisher.arrange import profiles
from flpfinisher.arrange.permissions import PermissionDenied
from flpfinisher.arrange.planner import build_plan
from flpfinisher.classify.signals import analyse_project
from flpfinisher.fs.safety import sha256_file
from flpfinisher.health.check import classify_state
from flpfinisher.model.schemas import PermissionLevel, PlaylistOp
from flpfinisher.parse.pyflp_backend import PyFLPBackend
from flpfinisher.validate.validator import notes_unchanged, validate_derivative
from flpfinisher.write.eventstream import (
    MalformedFLP,
    diff_events,
    read_flp,
    read_varint,
    write_flp,
    write_varint,
)
from flpfinisher.write.flp_writer import (
    WriteUnsupported,
    detect_item_size,
    plan_to_clips,
    write_arrangement,
)
from tests.fixtures.projects import PPQ, already_arranged, full_kit, melody_only


@pytest.fixture
def backend():
    return PyFLPBackend()


@pytest.fixture
def source(make_flp):
    return make_flp(full_kit(), "Starfall.flp")


@pytest.fixture
def prepared(backend, source):
    project = backend.parse(source)
    analysis = analyse_project(project, classify_state(project))
    plan = build_plan(project, analysis, profiles.load("hiphop"))
    return project, analysis, plan


# -- event stream ----------------------------------------------------------- #

@pytest.mark.parametrize("value", [0, 1, 127, 128, 255, 16384, 2_000_000])
def test_varint_round_trip(value):
    encoded = write_varint(value)
    assert read_varint(encoded, 0) == (value, len(encoded))


def test_reading_and_rewriting_is_byte_identical(source, tmp_path):
    flp = read_flp(source)
    out = write_flp(flp, tmp_path / "copy.flp")
    assert out.read_bytes() == source.read_bytes()


def test_diff_is_empty_for_an_unchanged_file(source, tmp_path):
    flp = read_flp(source)
    assert diff_events(flp, read_flp(write_flp(flp, tmp_path / "c.flp"))) == []


def test_corrupt_headers_are_rejected(tmp_path):
    bad = tmp_path / "bad.flp"
    bad.write_bytes(b"XXXX" + b"\0" * 40)
    with pytest.raises(MalformedFLP, match="FLhd"):
        read_flp(bad)


def test_a_truncated_data_chunk_is_rejected(source, tmp_path):
    bad = tmp_path / "short.flp"
    bad.write_bytes(source.read_bytes()[:-20])
    with pytest.raises(MalformedFLP, match="size mismatch"):
        read_flp(bad)


# -- clip generation -------------------------------------------------------- #

def test_tiles_expand_into_whole_pattern_repetitions(prepared):
    project, _, plan = prepared
    clips = plan_to_clips(plan, project)
    assert clips
    bar = PPQ * 4
    for position, _pattern, length, _track in clips:
        assert length % bar == 0
        assert position % bar == 0


def test_a_tile_never_extends_past_its_section(prepared):
    project, _, plan = prepared
    clips = plan_to_clips(plan, project)
    bar = PPQ * 4
    spans = {
        (op.start_bar, op.bars) for op in plan.ops
        if op.op == "tile" and op.start_bar and op.bars
    }
    limit = max((s - 1) * bar + b * bar for s, b in spans)
    assert all(p + length <= limit for p, _, length, _ in clips)


def test_clips_are_sorted_by_position(prepared):
    project, _, plan = prepared
    clips = plan_to_clips(plan, project)
    assert clips == sorted(clips)


def test_item_size_matches_the_source(source):
    size, tail = detect_item_size(read_flp(source))
    assert size in (32, 60)
    assert tail == b"" or len(tail) == 28


# -- the derivative --------------------------------------------------------- #

def test_writing_a_derivative_leaves_the_source_untouched(prepared, source, tmp_path):
    project, _, plan = prepared
    before = sha256_file(source)
    write_arrangement(source, tmp_path / "out.flp", plan, project)
    assert sha256_file(source) == before


def test_the_derivative_preserves_everything_but_the_playlist(
    prepared, source, backend, tmp_path
):
    project, _, plan = prepared
    out = tmp_path / "out.flp"
    write_arrangement(source, out, plan, project)
    rebuilt = backend.parse(out)

    assert len(rebuilt.patterns) == len(project.patterns)
    assert len(rebuilt.channels) == len(project.channels)
    assert len(rebuilt.mixer) == len(project.mixer)
    assert rebuilt.note_count == project.note_count
    assert rebuilt.tempo == project.tempo
    assert rebuilt.ppq == project.ppq
    assert rebuilt.fl_version == project.fl_version


def test_note_content_is_byte_identical(prepared, source, backend, tmp_path):
    """The Level 0 guarantee, checked directly."""
    project, _, plan = prepared
    out = tmp_path / "out.flp"
    write_arrangement(source, out, plan, project)
    assert notes_unchanged(project, backend.parse(out))


def test_tiling_length_is_quantised_to_whole_bars(prepared):
    """A pattern measured at 1464 ticks is still a four-bar pattern.

    Tiling at the measured extent would drift every repetition off the grid.
    """
    project, _, _plan = prepared
    from flpfinisher.write.flp_writer import _pattern_lengths

    bar = PPQ * 4
    measured = {p.index: p.length_ticks for p in project.patterns}
    assert any(v % bar for v in measured.values()), "fixture should have a ragged pattern"
    assert all(v % bar == 0 for v in _pattern_lengths(project).values())


def test_repeated_tiles_stay_on_the_bar_grid(prepared):
    project, _, plan = prepared
    bar = PPQ * 4
    by_pattern: dict[int, list[int]] = {}
    for position, pattern, _length, _track in plan_to_clips(plan, project):
        by_pattern.setdefault(pattern, []).append(position)
    for positions in by_pattern.values():
        assert all(p % bar == 0 for p in positions)


def test_the_playlist_is_replaced_not_appended(backend, make_flp, tmp_path):
    source = make_flp(already_arranged(), "Arranged.flp")
    project = backend.parse(source)
    analysis = analyse_project(project, classify_state(project))
    plan = build_plan(project, analysis, profiles.load("hiphop"))
    before = sum(len(a.clips) for a in project.arrangements)

    out = tmp_path / "out.flp"
    report = write_arrangement(source, out, plan, project)
    after = sum(len(a.clips) for a in backend.parse(out).arrangements)
    assert after == report.clips_written != before


def test_the_file_header_is_copied_verbatim(prepared, source, tmp_path):
    project, _, plan = prepared
    out = tmp_path / "out.flp"
    write_arrangement(source, out, plan, project)
    assert read_flp(out).header == read_flp(source).header


def test_section_markers_are_written(prepared, source, backend, tmp_path):
    project, _, plan = prepared
    out = tmp_path / "out.flp"
    report = write_arrangement(source, out, plan, project)
    assert report.markers_written == len(plan.sections)
    markers = [m.name for a in backend.parse(out).arrangements for m in a.markers]
    assert markers == [s.name.value.upper() for s in plan.sections]


def test_markers_can_be_turned_off(prepared, source, tmp_path):
    project, _, plan = prepared
    report = write_arrangement(source, tmp_path / "o.flp", plan, project, markers=False)
    assert report.markers_written == 0


def test_rebuilding_does_not_accumulate_markers(prepared, source, backend, tmp_path):
    project, _, plan = prepared
    first = tmp_path / "a.flp"
    write_arrangement(source, first, plan, project)
    second = tmp_path / "b.flp"
    write_arrangement(first, second, plan, backend.parse(first))
    markers = [m for a in backend.parse(second).arrangements for m in a.markers]
    assert len(markers) == len(plan.sections)


def test_the_operation_log_records_every_tile(prepared, source, tmp_path):
    project, _, plan = prepared
    report = write_arrangement(source, tmp_path / "o.flp", plan, project)
    tiles = sum(1 for op in plan.ops if op.op == "tile")
    assert sum(1 for line in report.operations if line.startswith("TILE_PATTERN")) == tiles
    # A source with no playlist gets one created; one with a playlist has it replaced.
    assert any(
        line.startswith(("CREATE_PLAYLIST", "REPLACE_PLAYLIST"))
        for line in report.operations
    )


def test_the_writer_refuses_a_plan_above_its_level(prepared, source, tmp_path):
    project, _, plan = prepared
    smuggled = plan.model_copy(
        update={"ops": (*plan.ops, PlaylistOp(op="remove_notes"))}
    )
    with pytest.raises(PermissionDenied):
        write_arrangement(source, tmp_path / "o.flp", smuggled, project)
    assert not (tmp_path / "o.flp").exists()


def test_a_plan_whose_patterns_do_not_exist_is_refused(prepared, source, tmp_path):
    project, _, plan = prepared
    orphaned = plan.model_copy(
        update={"ops": tuple(
            op.model_copy(update={"pattern": 999}) if op.op == "tile" else op
            for op in plan.ops
        )}
    )
    with pytest.raises(WriteUnsupported, match="no playlist clips"):
        write_arrangement(source, tmp_path / "o.flp", orphaned, project)


def test_a_project_with_one_pattern_still_writes(backend, make_flp, tmp_path):
    source = make_flp(melody_only(), "Sketch.flp")
    project = backend.parse(source)
    analysis = analyse_project(project, classify_state(project))
    plan = build_plan(project, analysis, profiles.load("rnb"))
    report = write_arrangement(source, tmp_path / "o.flp", plan, project)
    assert report.clips_written > 0


# -- validation ------------------------------------------------------------- #

def test_validation_passes_for_a_good_derivative(prepared, source, backend, tmp_path):
    project, _, plan = prepared
    out = tmp_path / "out.flp"
    digest = sha256_file(source)
    write_arrangement(source, out, plan, project)
    result = validate_derivative(source, out, project, plan, backend, source_hash=digest)
    assert result.passed, [c for c in result.checks if c.ok is False]


def test_validation_fails_when_the_output_is_not_parseable(
    prepared, source, backend, tmp_path
):
    project, _, plan = prepared
    broken = tmp_path / "broken.flp"
    broken.write_bytes(b"NOTANFLP")
    result = validate_derivative(
        source, broken, project, plan, backend, source_hash=sha256_file(source)
    )
    assert not result.passed


def test_validation_notices_a_changed_source(prepared, source, backend, tmp_path):
    project, _, plan = prepared
    out = tmp_path / "out.flp"
    write_arrangement(source, out, plan, project)
    result = validate_derivative(
        source, out, project, plan, backend, source_hash="0" * 64,
    )
    assert not result.passed
    check = next(c for c in result.checks if c.name == "source_unchanged")
    assert check.ok is False


def test_validation_checks_the_planned_length(prepared, source, backend, tmp_path):
    project, _, plan = prepared
    out = tmp_path / "out.flp"
    write_arrangement(source, out, plan, project)
    result = validate_derivative(
        source, out, project, plan, backend, source_hash=sha256_file(source)
    )
    length = next(c for c in result.checks if c.name == "length_matches_plan")
    assert length.ok is True


def test_level_one_writer_gate_is_declared():
    from flpfinisher.write.flp_writer import level_permits_note_edits

    assert not level_permits_note_edits(PermissionLevel.STRUCTURE_ONLY)
    assert level_permits_note_edits(PermissionLevel.CONSERVATIVE)

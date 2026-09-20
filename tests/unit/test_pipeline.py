"""The vertical slice: drop a .flp, get normalised analysis, touch nothing else."""

import json

import pytest
from fixtures.flp_builder import multi_pattern_loop, one_pattern_loop, write_flp

from prosody_core.fs.safety import CorpusMutated, sha256_file
from prosody_core.model.schemas import BeatProject
from prosody_core.pipeline import (
    inspect_project,
    scan_directory,
    write_scan_errors,
    write_scan_report,
)


def test_inspect_returns_project_analysis_and_health(make_flp, tmp_path):
    result = inspect_project(make_flp(multi_pattern_loop()), out_root=tmp_path / "out")
    assert result.project.tempo == 92.0
    assert result.analysis.project_id == result.project.id
    assert result.health.project_id == result.project.id


def test_inspect_writes_nothing_when_no_out_root_is_given(make_flp, tmp_path):
    source = make_flp(one_pattern_loop())
    before = set(tmp_path.rglob("*"))
    result = inspect_project(source)
    assert result.out_dir is None
    assert set(tmp_path.rglob("*")) == before


def test_inspect_never_modifies_the_source(make_flp, tmp_path):
    path = make_flp(multi_pattern_loop())
    before = sha256_file(path)
    inspect_project(path, out_root=tmp_path / "out")
    assert sha256_file(path) == before


def test_all_artifacts_land_under_out_slug(make_flp, tmp_path):
    out = tmp_path / "out"
    result = inspect_project(make_flp(multi_pattern_loop(), "My Beat.flp"), out_root=out)
    assert result.out_dir == out / "my-beat"
    written = {p.relative_to(result.out_dir).as_posix()
               for p in result.out_dir.rglob("*") if p.is_file()}
    assert written == {
        "DATA/project.json",
        "DATA/analysis.json",
        "REPORTS/health.json",
        "REPORTS/missing-files.txt",
        "REPORTS/plugins.txt",
    }


def test_written_project_json_round_trips_through_the_model(make_flp, tmp_path):
    result = inspect_project(make_flp(multi_pattern_loop()), out_root=tmp_path / "out")
    raw = json.loads((result.out_dir / "DATA" / "project.json").read_text())
    restored = BeatProject.model_validate(raw)
    assert restored == result.project


def test_missing_files_report_lists_unresolved_samples(make_flp, tmp_path):
    result = inspect_project(make_flp(multi_pattern_loop()), out_root=tmp_path / "out")
    listed = (result.out_dir / "REPORTS" / "missing-files.txt").read_text().split()
    assert listed == ["D:\\Drums\\Kick.wav"]


def test_a_source_mutated_mid_run_fails_the_run(make_flp, tmp_path, monkeypatch):
    path = make_flp(one_pattern_loop())

    # Simulate a stage writing to the source: the guard must catch it.
    import prosody_core.pipeline as pipeline

    original = pipeline.write_artifacts
    monkeypatch.setattr(
        pipeline, "write_artifacts",
        lambda *a, **k: (path.write_bytes(b"tampered"), original(*a, **k))[1],
    )
    with pytest.raises(CorpusMutated):
        inspect_project(path, out_root=tmp_path / "out")


# -- scan ------------------------------------------------------------------- #

def test_scan_parses_every_file_and_reports_the_rate(all_fixture_flps, tmp_path):
    root = next(iter(all_fixture_flps.values())).parent
    rows = scan_directory(root, out_root=tmp_path / "out")
    assert len(rows) == len(all_fixture_flps)
    assert all(row.ok for row in rows)


def test_one_unparseable_file_does_not_stop_the_batch(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write_flp(one_pattern_loop(), corpus / "good.flp")
    write_flp(multi_pattern_loop(), corpus / "also_good.flp")
    (corpus / "broken.flp").write_bytes(b"NOTANFLP" + b"\x00" * 32)

    rows = scan_directory(corpus, out_root=tmp_path / "out")
    assert len(rows) == 3
    assert sum(1 for r in rows if r.ok) == 2
    failed = next(r for r in rows if not r.ok)
    assert failed.path.name == "broken.flp"
    assert failed.error
    assert failed.sha256  # still hashed, even though it would not parse


def test_scan_report_csv_has_a_row_per_file(all_fixture_flps, tmp_path):
    root = next(iter(all_fixture_flps.values())).parent
    rows = scan_directory(root, out_root=tmp_path / "out")
    csv_path = write_scan_report(rows, tmp_path / "out" / "scan_report.csv")
    lines = csv_path.read_text().strip().splitlines()
    assert len(lines) == len(rows) + 1
    assert lines[0].startswith("path,sha256,ok,")


def test_scan_errors_log_records_failures_verbatim(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "broken.flp").write_bytes(b"NOTANFLP")
    rows = scan_directory(corpus, out_root=tmp_path / "out")
    log = write_scan_errors(rows, tmp_path / "out" / "scan_errors.log")
    text = log.read_text()
    assert "broken.flp" in text
    assert "HeaderCorrupted" in text


def test_scan_leaves_every_source_untouched(all_fixture_flps, tmp_path):
    before = {p: sha256_file(p) for p in all_fixture_flps.values()}
    root = next(iter(all_fixture_flps.values())).parent
    scan_directory(root, out_root=tmp_path / "out", write_artifacts_per_project=True)
    assert {p: sha256_file(p) for p in before} == before


def test_scan_of_an_empty_directory_returns_no_rows(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert scan_directory(empty, out_root=tmp_path / "out") == []

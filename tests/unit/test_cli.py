"""CLI surface. Commands stay thin; these check wiring, exit codes and safety."""

from fixtures.flp_builder import multi_pattern_loop, one_pattern_loop, write_flp
from typer.testing import CliRunner

from prosody_core.cli import app
from prosody_core.fs.safety import sha256_file

runner = CliRunner()


def test_doctor_reports_the_environment():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    for expected in ("platform", "pyflp", "FL Studio", "FL CLI switches"):
        assert expected in result.stdout


def test_doctor_flags_the_unconfirmed_midi_switch():
    result = runner.invoke(app, ["doctor"])
    assert "UNCONFIRMED" in result.stdout


def test_doctor_fails_when_render_is_demanded_without_fl(monkeypatch):
    monkeypatch.setenv("FLPF_RENDER", "1")
    result = runner.invoke(app, ["doctor"])
    # On a machine without FL Studio this must be a hard failure, not a warning.
    from prosody_core.env import find_fl_executable

    if find_fl_executable()[0] is None:
        assert result.exit_code == 1


def test_inspect_prints_a_summary(tmp_path):
    path = write_flp(multi_pattern_loop(), tmp_path / "beat.flp")
    result = runner.invoke(app, ["inspect", str(path), "--out", str(tmp_path / "out")])
    assert result.exit_code == 0
    assert "92 BPM" in result.stdout
    assert "REQUIRES_FREEZE" in result.stdout


def test_inspect_does_not_modify_the_source(tmp_path):
    path = write_flp(multi_pattern_loop(), tmp_path / "beat.flp")
    before = sha256_file(path)
    runner.invoke(app, ["inspect", str(path), "--out", str(tmp_path / "out")])
    assert sha256_file(path) == before


def test_inspect_no_write_leaves_the_out_root_absent(tmp_path):
    path = write_flp(one_pattern_loop(), tmp_path / "beat.flp")
    out = tmp_path / "out"
    result = runner.invoke(app, ["inspect", str(path), "--out", str(out), "--no-write"])
    assert result.exit_code == 0
    assert not out.exists()


def test_inspect_json_emits_parseable_project_json(tmp_path):
    import json

    path = write_flp(one_pattern_loop(), tmp_path / "beat.flp")
    result = runner.invoke(
        app, ["inspect", str(path), "--json", "--no-write"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["tempo"] == 140.0


def test_inspect_of_a_missing_file_exits_2(tmp_path):
    result = runner.invoke(app, ["inspect", str(tmp_path / "nope.flp")])
    assert result.exit_code == 2


def test_inspect_of_a_corrupt_file_exits_1(tmp_path):
    bad = tmp_path / "bad.flp"
    bad.write_bytes(b"NOTANFLP")
    result = runner.invoke(app, ["inspect", str(bad), "--no-write"])
    assert result.exit_code == 1


def test_scan_reports_the_parse_rate(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write_flp(one_pattern_loop(), corpus / "a.flp")
    write_flp(multi_pattern_loop(), corpus / "b.flp")
    result = runner.invoke(app, ["scan", str(corpus), "--out", str(tmp_path / "out")])
    assert result.exit_code == 0
    assert "parse rate: 2/2 (100%)" in result.stdout
    assert (tmp_path / "out" / "scan_report.csv").is_file()
    assert (tmp_path / "out" / "scan_errors.log").is_file()


def test_scan_of_a_missing_directory_exits_2(tmp_path):
    result = runner.invoke(app, ["scan", str(tmp_path / "nope")])
    assert result.exit_code == 2


def test_scan_of_a_directory_with_no_flps_exits_2(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["scan", str(empty), "--out", str(tmp_path / "out")])
    assert result.exit_code == 2

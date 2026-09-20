"""Originals are immutable and outputs are contained. Both enforced, not assumed."""

from pathlib import Path

import pytest

from prosody_core.fs.safety import (
    CorpusMutated,
    ReadOnlyCorpus,
    find_flps,
    output_dir,
    sha256_file,
    slugify,
    versioned_path,
)


def test_sha256_matches_hashlib(tmp_path: Path):
    import hashlib

    f = tmp_path / "a.bin"
    f.write_bytes(b"hello world" * 1000)
    assert sha256_file(f) == hashlib.sha256(f.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Starfall", "starfall"),
        ("beat_v7 FINAL (2)", "beat-v7-final-2"),
        ("  ...  ", "untitled"),
        ("C:/x/My Beat.flp", "c-x-my-beat-flp"),
    ],
)
def test_slugify(raw, expected):
    assert slugify(raw) == expected


def test_find_flps_is_recursive_sorted_and_case_insensitive(tmp_path: Path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "b.flp").write_bytes(b"")
    (tmp_path / "a.FLP").write_bytes(b"")
    (tmp_path / "nested" / "c.flp").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")
    assert [p.name for p in find_flps(tmp_path)] == ["a.FLP", "b.flp", "c.flp"]


def test_find_flps_accepts_a_single_file(tmp_path: Path):
    f = tmp_path / "one.flp"
    f.write_bytes(b"")
    assert find_flps(f) == [f]
    assert find_flps(tmp_path / "other.txt") == []


def test_output_dir_is_under_the_out_root(tmp_path: Path):
    out = output_dir(tmp_path / "out", Path("/corpus/2023/My Beat.flp"))
    assert out == tmp_path / "out" / "my-beat"
    assert out.is_dir()


def test_versioned_path_never_overwrites(tmp_path: Path):
    first = versioned_path(tmp_path, "SOURCE__RNB", ".flp")
    assert first.name == "SOURCE__RNB_V001.flp"
    first.write_bytes(b"x")
    second = versioned_path(tmp_path, "SOURCE__RNB", ".flp")
    assert second.name == "SOURCE__RNB_V002.flp"
    assert first.read_bytes() == b"x"


def test_corpus_guard_passes_when_nothing_changes(tmp_path: Path):
    f = tmp_path / "s.flp"
    f.write_bytes(b"original")
    guard = ReadOnlyCorpus.snapshot([f])
    f.read_bytes()
    guard.verify()
    assert guard.changed() == []


def test_corpus_guard_detects_a_modified_source(tmp_path: Path):
    f = tmp_path / "s.flp"
    f.write_bytes(b"original")
    guard = ReadOnlyCorpus.snapshot([f])
    f.write_bytes(b"tampered")
    assert guard.changed() == [f]
    with pytest.raises(CorpusMutated, match="changed during the run"):
        guard.verify()


def test_corpus_guard_detects_a_deleted_source(tmp_path: Path):
    f = tmp_path / "s.flp"
    f.write_bytes(b"original")
    guard = ReadOnlyCorpus.snapshot([f])
    f.unlink()
    with pytest.raises(CorpusMutated):
        guard.verify()

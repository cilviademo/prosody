"""FL Studio discovery must find an edition it has never heard of.

TESTING_HANDOFF P0.3: the studio PC has FL Studio 2026 at the conventional
path and Prosody reported "not in the registry, the default install folders,
or PATH". The edition list stopped at 2025. Discovery now globs.
"""

from __future__ import annotations

from pathlib import Path

from prosody_core import env
from tests.fixtures.binaries import fake_fl


def _installs(root: Path, *editions: tuple[str, str, str]) -> tuple[str, str]:
    pf, pf86 = root / "Program Files", root / "Program Files (x86)"
    for where, edition, exe in editions:
        folder = (pf if where == "64" else pf86) / "Image-Line" / edition
        folder.mkdir(parents=True, exist_ok=True)
        fake_fl(folder, name=exe)
    return str(pf), str(pf86)


def test_an_unlisted_edition_is_found_and_preferred(tmp_path):
    roots = _installs(
        tmp_path, ("64", "FL Studio 2026", "FL64.exe"), ("64", "FL Studio 21", "FL64.exe"),
        ("86", "FL Studio 20", "FL.exe"),
    )
    found = env.discover_fl_candidates(program_roots=roots)
    assert [c.path.parent.name for c in found] == ["FL Studio 2026", "FL Studio 21", "FL Studio 20"]
    assert found[0].path.name == "FL64.exe"


def test_find_fl_executable_reports_the_newest_and_names_the_others(tmp_path, monkeypatch):
    roots = _installs(tmp_path, ("64", "FL Studio 2026", "FL64.exe"), ("64", "FL Studio 2024", "FL64.exe"))
    monkeypatch.delenv("FLPF_FL_EXE", raising=False)
    monkeypatch.setattr(env, "PROGRAM_ROOTS", roots)
    path, how = env.find_fl_executable()
    assert path is not None and path.parent.name == "FL Studio 2026"
    assert "install folder" in how
    assert "also found: FL Studio 2024" in how


def test_a_future_edition_beats_a_known_one(tmp_path):
    roots = _installs(tmp_path, ("64", "FL Studio 2025", "FL64.exe"), ("64", "FL Studio 2031", "FL64.exe"))
    assert env.discover_fl_candidates(program_roots=roots)[0].path.parent.name == "FL Studio 2031"


def test_the_override_still_wins(tmp_path, monkeypatch):
    roots = _installs(tmp_path, ("64", "FL Studio 2026", "FL64.exe"))
    override = fake_fl(tmp_path, name="FL64.exe")
    monkeypatch.setenv("FLPF_FL_EXE", str(override))
    monkeypatch.setattr(env, "PROGRAM_ROOTS", roots)
    path, how = env.find_fl_executable()
    assert path == override and "override" in how


def test_nothing_installed_keeps_the_bare_reason(tmp_path, monkeypatch):
    (tmp_path / "Program Files" / "Image-Line").mkdir(parents=True)
    monkeypatch.delenv("FLPF_FL_EXE", raising=False)
    monkeypatch.setattr(env, "PROGRAM_ROOTS", (str(tmp_path / "Program Files"),))
    monkeypatch.setattr(env.shutil, "which", lambda _n: None)
    path, how = env.find_fl_executable()
    assert path is None
    assert "not found" not in how          # callers compose the sentence


def test_edition_numbers_parse_from_folder_names():
    assert env._edition_number(Path("FL Studio 2026")) == (2026,)
    assert env._edition_number(Path("FL Studio 21")) == (21,)
    assert env._edition_number(Path("Image-Line Stuff")) == ()


def test_rank_prefers_a_real_file_version_over_the_folder_name():
    a = env.FLCandidate(Path("x/FL Studio 21/FL64.exe"), "test", "21.2.3.4004")
    b = env.FLCandidate(Path("x/FL Studio 2026/FL64.exe"), "test", None)
    assert b.rank > a.rank
    assert a.rank == (21, 2, 3, 4004)


def test_the_edition_list_now_includes_2026():
    assert "FL Studio 2026" in env.FL_EDITIONS
    assert any("2026" in root for root in env.windows_install_roots())

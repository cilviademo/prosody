"""HARDENING P0 guarantees, asserted rather than assumed.

Each test here corresponds to a numbered requirement in HARDENING.md. They are
deliberately blunt: they check the shipped behaviour, not the implementation.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

from prosody_core import buildinfo
from prosody_core.fs import pe

REPO = Path(__file__).resolve().parent.parent.parent


# --- P0.1: architecture guard ---------------------------------------------- #

def _pe_bytes(machine: int, lfanew: int = 0x80) -> bytes:
    """A byte sequence with a valid-enough PE header for the reader."""
    data = bytearray(lfanew + 64)
    data[0:2] = b"MZ"
    data[0x3C:0x40] = struct.pack("<I", lfanew)
    data[lfanew:lfanew + 4] = b"PE\0\0"
    data[lfanew + 4:lfanew + 6] = struct.pack("<H", machine)
    return bytes(data)


@pytest.mark.parametrize(
    ("machine", "ok", "fragment"),
    [
        (pe.MACHINE_AMD64, True, "x64"),
        (pe.MACHINE_ARM64, True, "ARM64"),
        (pe.MACHINE_I386, False, "32-bit"),
        (0x01C0, False, "0x01C0"),
    ],
)
def test_pe_machine_types_are_named(tmp_path, machine, ok, fragment):
    exe = tmp_path / "FL64.exe"
    exe.write_bytes(_pe_bytes(machine))
    got_ok, description = pe.describe(exe)
    assert got_ok is ok
    assert fragment in description


def test_a_non_windows_binary_is_not_mistaken_for_a_program(tmp_path):
    """An ELF named .exe is the packaging mistake this guard exists for."""
    exe = tmp_path / "prosody-core.exe"
    exe.write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64)
    assert pe.describe(exe) == (False, "not a Windows program")


def test_the_header_offset_is_read_not_assumed(tmp_path):
    """Real binaries put the PE header wherever the linker chose."""
    exe = tmp_path / "a.exe"
    exe.write_bytes(_pe_bytes(pe.MACHINE_AMD64, lfanew=0x108))
    assert pe.machine_type(exe) == pe.MACHINE_AMD64


def test_a_truncated_file_does_not_raise(tmp_path):
    exe = tmp_path / "cut.exe"
    exe.write_bytes(b"MZ")
    assert pe.machine_type(exe) is None


def test_a_missing_file_does_not_raise(tmp_path):
    assert pe.machine_type(tmp_path / "nope.exe") is None


# --- P0.1: no global runtimes ---------------------------------------------- #

def test_the_release_shell_never_looks_for_python_on_path():
    """A shipped Prosody may start only its own core, FL, and the opener.

    The run-from-source path is real and useful, but it must not be compiled
    into a release: a user whose extracted folder happens to sit under a
    directory containing pyproject.toml would otherwise have their own Python
    launched.
    """
    source = (REPO / "apps" / "desktop" / "src-tauri" / "src" / "core.rs").read_text(encoding="utf-8")
    for name in ("fn interpreter", "fn repo_root"):
        index = source.index(name)
        preceding = source[:index].rsplit("\n\n", 1)[-1]
        assert "#[cfg(debug_assertions)]" in preceding, (
            f"{name} is compiled into release builds; it searches PATH for an interpreter"
        )


def test_no_shell_interpreter_is_ever_spawned():
    """HARDENING P0.5: no shell=True, and no cmd/powershell/sh trampolines."""
    offenders: list[str] = []

    for rust in (REPO / "apps" / "desktop" / "src-tauri" / "src").glob("*.rs"):
        text = rust.read_text(encoding="utf-8")
        for needle in ('Command::new("cmd")', 'Command::new("powershell")', 'Command::new("sh")'):
            if needle in text:
                offenders.append(f"{rust.name}: {needle}")

    for py in (REPO / "prosody_core").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "shell=True" in text:
            offenders.append(f"{py.relative_to(REPO)}: shell=True")

    assert not offenders, "a shell interpreter is spawned with user data:\n  " + "\n  ".join(offenders)


def test_the_core_is_spawned_with_utf8_mode():
    """Without PYTHONUTF8 a project path outside the ANSI code page is unopenable."""
    source = (REPO / "apps" / "desktop" / "src-tauri" / "src" / "core.rs").read_text(encoding="utf-8")
    assert '.env("PYTHONUTF8", "1")' in source


# --- P0.1: build manifest --------------------------------------------------- #

def test_a_development_run_reports_itself_as_one():
    info = buildinfo.describe()
    assert info.frozen is False
    assert info.values["build"] == "development"
    assert info.warnings == ()


def test_a_packaged_build_verifies_its_own_hash(tmp_path, monkeypatch):
    core = tmp_path / "prosody-core.exe"
    core.write_bytes(b"pretend this is thirty megabytes")
    digest = buildinfo.sha256(core)
    (tmp_path / "build-info.json").write_text(
        json.dumps({"build": "release", "prosodyVersion": "0.1.0", "coreSha256": digest}),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(core))

    info = buildinfo.describe()
    assert info.frozen is True
    assert info.hash_matches is True
    assert info.warnings == ()
    assert info.values["prosodyVersion"] == "0.1.0"


def test_a_modified_core_is_reported_and_does_not_stop_startup(tmp_path, monkeypatch):
    core = tmp_path / "prosody-core.exe"
    core.write_bytes(b"original")
    (tmp_path / "build-info.json").write_text(
        json.dumps({"build": "release", "coreSha256": buildinfo.sha256(core)}),
        encoding="utf-8",
    )
    core.write_bytes(b"tampered with, or rewritten by antivirus")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(core))

    info = buildinfo.describe()
    assert info.hash_matches is False
    assert any("does not match" in w for w in info.warnings)


def test_a_packaged_build_without_a_manifest_says_so(tmp_path, monkeypatch):
    core = tmp_path / "prosody-core.exe"
    core.write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(core))
    info = buildinfo.describe()
    assert info.frozen is True
    assert any("build-info.json" in w for w in info.warnings)


# --- P0.2: the index is an index, never the source of truth ---------------- #

from prosody_core.api import HANDLERS  # noqa: E402
from prosody_core.index import db  # noqa: E402


def test_a_fresh_database_passes_its_integrity_check(tmp_path):
    path = tmp_path / "prosody.db"
    assert db.check_integrity(path).ok  # nothing there yet
    db.migrate(path)
    assert db.check_integrity(path) == (True, None, "ok")


def test_the_index_uses_wal_so_an_interrupted_build_cannot_tear_a_page(tmp_path):
    path = tmp_path / "prosody.db"
    db.migrate(path)
    with db.connect(path) as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


@pytest.mark.parametrize(
    ("name", "damage"),
    [
        ("bad header", lambda b: b"NOTASQLITEFILE\x00\x00" + b[16:]),
        ("truncated", lambda b: b[: len(b) // 2 + 7]),
        ("not a database", lambda b: b"hello"),
    ],
)
def test_a_corrupt_index_is_set_aside_and_rebuilt_not_fatal(tmp_path, name, damage):
    path = tmp_path / "prosody.db"
    db.migrate(path)
    path.write_bytes(damage(path.read_bytes()))

    result = db.check_integrity(path)
    assert result.ok is False, name
    assert result.quarantined is not None and result.quarantined.exists()
    assert not path.exists(), "the corrupt file must be moved, not left in place"
    # And the replacement is usable immediately.
    assert db.migrate(path) == db.MIGRATIONS[-1][0]
    assert db.check_integrity(path).ok


def test_no_stale_wal_is_left_beside_the_replacement_database(tmp_path):
    """A -wal from the old database would corrupt the new one that replaces it.

    SQLite discards the siblings itself when the main file's header is
    unreadable, and check_integrity moves any it does not; what matters to the
    next startup is only that none are left at the original path.
    """
    path = tmp_path / "prosody.db"
    db.migrate(path)
    path.write_bytes(b"ruined")
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).write_bytes(b"stale")

    result = db.check_integrity(path)
    assert result.quarantined is not None
    for suffix in ("-wal", "-shm"):
        assert not Path(str(path) + suffix).exists(), f"a stale {suffix} survived"

    # And the replacement really is usable.
    assert db.migrate(path) == db.MIGRATIONS[-1][0]
    assert db.check_integrity(path).ok


def test_the_library_rebuilds_from_the_export_folder(tmp_path, make_flp):
    """Losing the database must cost nothing but the time to rescan."""
    from prosody_core.workspace import Workspace
    from tests.fixtures.projects import full_kit

    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    source = make_flp(full_kit())

    built = HANDLERS["build.run"]({"path": str(source), "genre": "rnb", "arrange": True}, workspace)
    assert built.get("outDir"), built

    before = HANDLERS["library.list"]({}, workspace)["projects"]
    assert before, "the build should have recorded a project"

    # Lose the database entirely, the way a corrupt one is lost.
    workspace.db_path.unlink()
    assert HANDLERS["library.list"]({}, workspace)["projects"] == []

    report = HANDLERS["library.rebuild"]({}, workspace)
    assert report["recovered"] >= 1, report
    assert report["skipped"] == [], report

    after = HANDLERS["library.list"]({}, workspace)["projects"]
    assert [p["id"] for p in after] == [p["id"] for p in before]
    assert [p["name"] for p in after] == [p["name"] for p in before]


# --- P0.2: Safe Mode -------------------------------------------------------- #

def test_safe_mode_is_off_unless_the_shell_says_otherwise(monkeypatch):
    monkeypatch.delenv("PROSODY_SAFE_MODE", raising=False)
    from prosody_core.env import describe
    assert describe({}).safe_mode is False


def test_safe_mode_refuses_to_write_anything(tmp_path, make_flp, monkeypatch):
    from prosody_core.build import SafeModeError
    from prosody_core.workspace import Workspace
    from tests.fixtures.projects import full_kit

    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    source = make_flp(full_kit())
    monkeypatch.setenv("PROSODY_SAFE_MODE", "1")

    with pytest.raises(SafeModeError) as raised:
        HANDLERS["build.run"]({"path": str(source), "genre": "rnb"}, workspace)
    assert "Safe Mode" in str(raised.value)
    assert "safemode.flag" in str(raised.value), "the message must say how to leave Safe Mode"

    # Nothing was created on the way to refusing.
    exports = workspace.export_root()
    assert not exports.exists() or not any(exports.iterdir())


def test_safe_mode_never_launches_fl(monkeypatch):
    from prosody_core.env import describe
    from prosody_core.extract import render_fl, stems

    monkeypatch.setenv("PROSODY_SAFE_MODE", "1")
    monkeypatch.setenv("FLPF_RENDER", "1")
    env = describe({"fl_executable": None, "render_enabled": True})

    can_render, reason = render_fl.availability(env)
    assert can_render is False
    assert "Safe Mode" in reason

    strategy, stem_reason = stems.available_strategy(env)
    assert strategy is None
    assert "Safe Mode" in stem_reason
    assert env.can_render is False


def test_safe_mode_still_allows_inspection(tmp_path, make_flp, monkeypatch):
    """Safe Mode is for getting your bearings, not a locked door."""
    from prosody_core.workspace import Workspace
    from tests.fixtures.projects import full_kit

    workspace = Workspace.open(tmp_path / "docs", tmp_path / "state")
    source = make_flp(full_kit())
    monkeypatch.setenv("PROSODY_SAFE_MODE", "1")

    inspected = HANDLERS["project.inspect"]({"path": str(source)}, workspace)
    assert inspected["tempo"] > 0
    assert inspected["counts"]
    assert HANDLERS["environment"]({}, workspace)["safeMode"] is True

    # HARDENING P0.2 allows Library in Safe Mode, and inspecting a project
    # records it — that is bookkeeping in the index, not a write to the user's
    # work. What Safe Mode forbids is producing output.
    assert [p["name"] for p in HANDLERS["library.list"]({}, workspace)["projects"]] == [source.stem]
    exports = workspace.export_root()
    assert not exports.exists() or not any(exports.iterdir()), "Safe Mode wrote an export"
    assert not list(source.parent.glob("*PROSODY*")), "Safe Mode wrote beside the source"


def test_the_shell_offers_three_ways_into_safe_mode():
    """A user who cannot start the app cannot use the app to change a setting."""
    source = (REPO / "apps" / "desktop" / "src-tauri" / "src" / "paths.rs").read_text(encoding="utf-8")
    assert '"--safe"' in source
    assert "safemode.flag" in source
    assert "GetAsyncKeyState" in source
    core = (REPO / "apps" / "desktop" / "src-tauri" / "src" / "core.rs").read_text(encoding="utf-8")
    assert '"PROSODY_SAFE_MODE"' in core, "the core is never told about Safe Mode"


def test_a_configured_fl_that_is_not_a_program_cannot_render(tmp_path):
    """The check runs on every platform, so this suite can see it.

    Gated on Windows, it was invisible here: a fixture writing an empty file
    named FL64.exe passed on Linux and failed the Windows release build.
    """
    from prosody_core.env import describe
    from tests.fixtures.binaries import MACHINE_I386, fake_fl

    empty = tmp_path / "FL64.exe"
    empty.write_bytes(b"")
    env = describe({"fl_executable": str(empty), "render_enabled": True})
    assert env.fl_architecture_ok is False
    assert env.can_render is False
    assert "not a Windows program" in str(env.fl_architecture)
    assert "not a Windows program" in env.fl_discovery

    thirty_two_bit = fake_fl(tmp_path, name="FL.exe", machine=MACHINE_I386)
    env = describe({"fl_executable": str(thirty_two_bit), "render_enabled": True})
    assert env.fl_architecture_ok is False
    assert "32-bit" in str(env.fl_architecture)

    real = fake_fl(tmp_path, name="FL64-ok.exe")
    env = describe({"fl_executable": str(real), "render_enabled": True})
    assert env.fl_architecture_ok is True
    assert env.can_render is True

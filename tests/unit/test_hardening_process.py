"""HARDENING P0.5: Prosody owns the processes it starts, and only those."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from prosody_core.extract import procguard, render_fl

# --- the timeout formula ---------------------------------------------------- #

def test_a_short_loop_still_gets_ten_minutes():
    """A cold FL with a heavy plugin set can take minutes before bar one."""
    assert render_fl.render_timeout(0.2) == render_fl.MIN_RENDER_TIMEOUT
    assert render_fl.render_timeout(0) == render_fl.MIN_RENDER_TIMEOUT


def test_a_long_song_gets_three_times_real_time():
    assert render_fl.render_timeout(10) == 10 * 60 * 3
    assert render_fl.render_timeout(60) == 60 * 60 * 3


def test_stems_multiply_the_allowance():
    """Each stem lane is another pass through the project."""
    assert render_fl.render_timeout(10, stem_count=4) > render_fl.render_timeout(10)


def test_a_negative_length_cannot_produce_a_zero_timeout():
    assert render_fl.render_timeout(-5) == render_fl.MIN_RENDER_TIMEOUT


# --- the disk check --------------------------------------------------------- #

def test_the_size_estimate_scales_with_length_and_stems():
    one = render_fl.estimate_render_bytes(1)
    assert one > 0
    assert render_fl.estimate_render_bytes(2) == pytest.approx(one * 2, rel=0.01)
    assert render_fl.estimate_render_bytes(1, stem_count=3) > one * 3


def test_a_render_that_would_not_fit_is_refused_before_fl_starts(tmp_path):
    ok, why = render_fl.disk_headroom(tmp_path, 1 << 60)  # an exabyte
    assert ok is False
    assert "free" in why and "needed" in why


def test_a_render_that_fits_is_allowed(tmp_path):
    ok, why = render_fl.disk_headroom(tmp_path, 1024)
    assert ok is True
    assert "free" in why


def test_the_check_works_for_a_folder_that_does_not_exist_yet(tmp_path):
    """The export folder is created by the build, after this check."""
    ok, _ = render_fl.disk_headroom(tmp_path / "not" / "made" / "yet", 1024)
    assert ok is True


def test_an_unstattable_path_does_not_block_the_render(tmp_path, monkeypatch):
    """A failed check must never be the reason a build cannot run."""
    import shutil as shutil_module

    monkeypatch.setattr(
        shutil_module, "disk_usage", lambda *a: (_ for _ in ()).throw(OSError("no"))
    )
    ok, why = render_fl.disk_headroom(tmp_path, 1 << 40)
    assert ok is True
    assert "could not check" in why


# --- owning the process ----------------------------------------------------- #

def test_the_guard_degrades_instead_of_failing_off_windows():
    with procguard.ProcessGuard() as guard:
        assert guard.active is (os.name == "nt")
        assert guard.reason
        # adopt() on an unavailable guard reports False rather than raising.
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        try:
            assert guard.adopt(process) in (True, False)
        finally:
            process.wait(timeout=30)


@pytest.mark.skipif(os.name != "nt", reason="job objects are a Windows feature")
def test_a_guarded_child_dies_when_the_job_closes():
    guard = procguard.ProcessGuard()
    assert guard.active, guard.reason
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    assert guard.adopt(process)
    guard.close()
    deadline = time.monotonic() + 30
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.2)
    assert process.poll() is not None, "closing the job did not stop the child"


def test_a_render_timeout_stops_the_process_and_reports_it(monkeypatch, tmp_path):
    """A wedged FL must be killed, not left running behind a failed build."""
    script = "import time; time.sleep(300)"
    code, _stdout, stderr, seconds = render_fl._run(
        [sys.executable, "-c", script], timeout=2
    )
    assert code is None
    assert "timed out" in stderr
    assert "stopped" in stderr
    assert seconds < 60


def test_an_unlaunchable_path_is_a_failed_render_not_an_exception(tmp_path):
    missing = tmp_path / "definitely" / "not" / "FL64.exe"
    code, _stdout, stderr, _seconds = render_fl._run([str(missing)], timeout=5)
    assert code is None
    assert "could not start FL Studio" in stderr


# --- no shell, ever --------------------------------------------------------- #

def test_fl_is_invoked_with_a_structured_argument_list():
    """A dropped filename is data. It must never become command syntax."""
    source = Path(render_fl.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "subprocess.Popen(" in source
    # The command is built as a list of parts, never joined into a string.
    assert 'command = [' in source


def test_the_exact_argv_is_recorded_for_diagnostics():
    result = render_fl.RenderResult(ok=False, command=["C:\\FL\\FL64.exe", "/Rout", "/Ewav"])
    log = result.as_log()
    assert log["argv"] == ["C:\\FL\\FL64.exe", "/Rout", "/Ewav"]


# --- a closed FL window is not a crash -------------------------------------- #

def test_fl_closed_mid_render_is_a_warning_with_advice(tmp_path, monkeypatch):
    from prosody_core.env import Environment

    env = Environment(
        platform="win32", python_version="3.12.0",
        fl_executable=tmp_path / "FL64.exe", fl_discovery="set in Settings",
        ffmpeg=None, pyflp_version="2.2.1", pyflp_compat_shim=False,
        render_enabled=True, gui_enabled=False,
    )
    (tmp_path / "FL64.exe").write_bytes(b"MZ")

    # FL ran, returned non-zero, wrote nothing: the closed-window signature.
    monkeypatch.setattr(render_fl, "_run", lambda *a, **k: (1, "", "", 3.0))
    result = render_fl.render_project(tmp_path / "x.flp", tmp_path / "out", env=env)

    assert result.ok is False
    assert result.closed_by_user is True
    assert "closed before it finished" in result.message
    assert "start the build again" in result.message


def test_a_genuine_nonzero_exit_with_output_is_not_blamed_on_the_user(tmp_path, monkeypatch):
    from prosody_core.env import Environment

    env = Environment(
        platform="win32", python_version="3.12.0",
        fl_executable=tmp_path / "FL64.exe", fl_discovery="set in Settings",
        ffmpeg=None, pyflp_version="2.2.1", pyflp_compat_shim=False,
        render_enabled=True, gui_enabled=False,
    )
    (tmp_path / "FL64.exe").write_bytes(b"MZ")
    out = tmp_path / "out"
    out.mkdir()

    def ran(*_a, **_k):
        (out / "x.wav").write_bytes(b"RIFF")
        return 3, "", "", 5.0

    monkeypatch.setattr(render_fl, "_run", ran)
    result = render_fl.render_project(tmp_path / "x.flp", out, env=env)
    assert result.closed_by_user is False
    assert "exited with 3" in result.message

"""FL Studio command-line wrapper.

FL Studio is the only renderer. This module shells out to it and captures
everything: command, exit code, stdout, stderr, wall time and the files that
appeared. It never invents audio, and it never claims success it did not see.

Switches (FL manual, Save/Export -> "command line"):
    /R<file>        render a project
    /E<fmt,fmt>     choose export formats
    /F<folder>      render every .flp in a folder

The MIDI-export switch is documented as existing but its letter has not been
confirmed on a real install, so :func:`export_midi` refuses rather than guessing
- per-role MIDI comes from ``extract.midi`` instead, which needs no FL at all.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from prosody_core.env import Environment, describe
from prosody_core.extract import procguard

DEFAULT_TIMEOUT = 600  # seconds; VST-heavy projects are slow


class RenderUnavailable(RuntimeError):
    """Rendering was requested where it cannot run."""


@dataclass
class RenderResult:
    ok: bool
    command: list[str] = field(default_factory=list)
    exit_code: int | None = None
    seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    outputs: list[Path] = field(default_factory=list)
    message: str = ""
    #: FL ran, failed, and wrote nothing — almost always a closed window.
    closed_by_user: bool = False

    def as_log(self) -> dict[str, object]:
        return {
            # The exact argv, so Diagnostics can show what was actually run
            # rather than a reconstruction (HARDENING P0.5).
            "argv": list(self.command),
            "command": " ".join(self.command),
            "closed_by_user": self.closed_by_user,
            "exit_code": self.exit_code,
            "seconds": round(self.seconds, 2),
            "outputs": [str(p) for p in self.outputs],
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-4000:],
        }


def availability(env: Environment | None = None) -> tuple[bool, str]:
    """(can_render, human-readable reason)."""
    env = env or describe()
    if env.safe_mode:
        return False, "Safe Mode is on, so FL Studio is never launched"
    if env.fl_executable is None:
        return False, f"FL Studio not found — {env.fl_discovery}"
    if not env.fl_architecture_ok:
        return False, f"the configured FL Studio is {env.fl_architecture}"
    if not env.render_enabled:
        return False, "rendering is turned off"
    return True, f"FL Studio at {env.fl_executable}"


#: Never less than ten minutes, because a cold FL Studio with a heavy plugin
#: set can take that long before it renders a single bar.
MIN_RENDER_TIMEOUT = 600


def render_timeout(project_minutes: float, stem_count: int = 0) -> int:
    """How long to wait for a render (HARDENING P0.5).

    Three times real time per minute of music, floored at ten minutes. Offline
    rendering is usually faster than real time, so this is generous — which is
    the point: killing a legitimate render is worse than waiting.
    """
    lanes = max(1, stem_count)
    estimate = 60.0 * max(0.0, project_minutes) * 3.0 * lanes
    return int(max(MIN_RENDER_TIMEOUT, estimate))


def estimate_render_bytes(
    minutes: float,
    *,
    sample_rate: int = 44_100,
    channels: int = 2,
    bytes_per_sample: int = 3,
    stem_count: int = 0,
) -> int:
    """Rough size of what a render will write, for the disk check."""
    seconds = max(0.0, minutes) * 60.0
    per_lane = seconds * sample_rate * channels * bytes_per_sample
    return int(per_lane * (1 + max(0, stem_count)) * 1.2)


def disk_headroom(destination: Path, needed_bytes: int) -> tuple[bool, str]:
    """Whether ``destination``'s volume has room, and what to say if not.

    Checked before FL is launched: a render that fills the disk half-way
    through leaves a truncated WAV and, worse, a machine with no space left
    for anything else.
    """
    try:
        usage = shutil.disk_usage(_existing_ancestor(destination))
    except OSError as exc:
        return True, f"could not check free space ({exc})"
    if usage.free >= needed_bytes:
        return True, f"{usage.free / 1e9:.1f} GB free, about {needed_bytes / 1e9:.1f} GB needed"
    return False, (
        f"about {needed_bytes / 1e9:.1f} GB is needed to render this and only "
        f"{usage.free / 1e9:.1f} GB is free on {_existing_ancestor(destination)}"
    )


def _existing_ancestor(path: Path) -> Path:
    """The nearest folder that exists, so disk_usage has something to stat."""
    candidate = Path(path)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _run(command: list[str], timeout: int) -> tuple[int | None, str, str, float]:
    """Run FL and capture everything. Never raises.

    A configured path can exist and still not be launchable — the wrong file
    picked in the dialog, a permissions problem, a half-copied install. That
    has to come back as a failed render with a readable reason, not an
    exception the UI reports as "internal".

    The process is put in a job object that terminates it if Prosody dies, so
    a crash cannot leave a headless FL Studio running with no window to find
    (HARDENING P0.5).
    """
    started = time.monotonic()
    creation_flags = 0
    if os.name == "nt":  # CREATE_NO_WINDOW: FL shows its own window anyway.
        creation_flags = 0x08000000

    try:
        with procguard.ProcessGuard() as guard:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creation_flags,
            )
            guard.adopt(process)
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill only what we started. The job object would do it when
                # this scope exits, but being explicit means the wait below
                # cannot hang.
                process.kill()
                stdout, stderr = process.communicate()
                return (
                    None,
                    stdout or "",
                    f"timed out after {timeout}s and was stopped",
                    time.monotonic() - started,
                )
    except OSError as exc:
        return None, "", f"could not start FL Studio: {exc.strerror or exc}", (
            time.monotonic() - started
        )

    return (
        process.returncode,
        stdout or "",
        stderr or "",
        time.monotonic() - started,
    )


def render_project(
    flp: Path,
    out_dir: Path,
    *,
    formats: tuple[str, ...] = ("wav",),
    env: Environment | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> RenderResult:
    """Render one project to ``out_dir`` in the requested formats."""
    env = env or describe()
    ok, reason = availability(env)
    if not ok:
        return RenderResult(ok=False, message=reason)

    flp = Path(flp)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / flp.stem

    command = [
        str(env.fl_executable),
        f"/R{target}",
        f"/E{','.join(formats)}",
    ]
    before = set(out_dir.iterdir())
    code, stdout, stderr, seconds = _run(command, timeout)
    produced = sorted(p for p in out_dir.iterdir() if p not in before and p.is_file())

    success = code == 0 and bool(produced)
    message = ""
    closed_by_user = False
    if code is None:
        message = stderr or "FL Studio did not run"
    elif code != 0 and not produced:
        # FL ran, ended with a non-zero code, and wrote nothing. By far the
        # commonest cause is the user closing FL's window while it rendered —
        # which is a thing that happened, not a fault to report as a crash
        # (HARDENING P0.5).
        closed_by_user = True
        message = (
            "FL Studio closed before it finished rendering. If you closed its "
            f"window, start the build again and leave it alone. (exit code {code})"
        )
    elif code != 0:
        message = f"FL Studio exited with {code}"
    elif not produced:
        message = "FL Studio exited cleanly but produced no files"

    return RenderResult(
        ok=success, command=command, exit_code=code, seconds=seconds,
        stdout=stdout, stderr=stderr, outputs=produced, message=message,
        closed_by_user=closed_by_user,
    )


def render_folder(
    folder: Path,
    *,
    formats: tuple[str, ...] = ("wav",),
    env: Environment | None = None,
    timeout: int = DEFAULT_TIMEOUT * 4,
) -> RenderResult:
    """Render every .flp in ``folder`` in one FL invocation (used for stems)."""
    env = env or describe()
    ok, reason = availability(env)
    if not ok:
        return RenderResult(ok=False, message=reason)

    folder = Path(folder)
    command = [str(env.fl_executable), f"/F{folder}", f"/E{','.join(formats)}"]
    before = set(folder.rglob("*"))
    code, stdout, stderr, seconds = _run(command, timeout)
    produced = sorted(
        p for p in folder.rglob("*")
        if p not in before and p.is_file() and p.suffix.lower() != ".flp"
    )

    return RenderResult(
        ok=code == 0 and bool(produced), command=command, exit_code=code,
        seconds=seconds, stdout=stdout, stderr=stderr, outputs=produced,
        message="" if produced else f"no audio produced (exit {code})",
    )


def export_midi(flp: Path, out_dir: Path, **_: object) -> RenderResult:
    """Not implemented: the FL MIDI-export switch letter is unconfirmed.

    ``extract.midi.write_role_midi`` produces per-role MIDI without FL Studio,
    so nothing in the product depends on this.
    """
    return RenderResult(
        ok=False,
        message=(
            "FL's MIDI-export switch has not been confirmed on a real install, "
            "so it is not invoked. Per-role MIDI is exported directly instead."
        ),
    )


def connection_test_project() -> Path | None:
    """The tiny bundled .flp used by Settings -> Test Connection.

    One bar of kick at 120 BPM: small enough that a pass or fail says something
    about FL Studio rather than about the project.
    """
    candidate = Path(__file__).resolve().parent.parent / "assets" / "connection-test.flp"
    return candidate if candidate.is_file() else None


@dataclass
class ConnectionTest:
    ok: bool
    detail: str
    seconds: float = 0.0
    output: str | None = None


def test_connection(
    env: Environment | None = None, *, timeout: int = 600,
) -> ConnectionTest:
    """Render the bundled test project and report what happened.

    This is the only honest way to answer "is FL Studio wired up?" — a path
    that exists proves nothing about whether it will render.
    """
    import tempfile

    env = env or describe()
    if env.fl_executable is None:
        return ConnectionTest(False, f"FL Studio not found — {env.fl_discovery}")

    project = connection_test_project()
    if project is None:
        return ConnectionTest(False, "the bundled test project is missing")

    with tempfile.TemporaryDirectory(prefix="prosody-fltest-") as tmp:
        work = Path(tmp)
        # Render a copy so the bundled asset is never touched.
        copy = work / project.name
        copy.write_bytes(project.read_bytes())

        # Test Connection must work before the user turns rendering on.
        probe = replace(env, render_enabled=True)
        result = render_project(copy, work, formats=("wav",), env=probe,
                                timeout=timeout)

        if result.ok and result.outputs:
            produced = result.outputs[0]
            return ConnectionTest(
                True,
                f"rendered {produced.name} in {result.seconds:.1f}s",
                result.seconds,
                produced.name,
            )
        detail = result.message or "FL Studio produced no audio"
        if result.exit_code is not None:
            detail = f"{detail} (exit {result.exit_code})"
        return ConnectionTest(False, detail, result.seconds)


def expected_duration_seconds(bars: float, tempo: float, beats_per_bar: int = 4) -> float:
    """``bars x beats x 60 / bpm`` - used to sanity-check a render."""
    if tempo <= 0:
        return 0.0
    return bars * beats_per_bar * 60.0 / tempo

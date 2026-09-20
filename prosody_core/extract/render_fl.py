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

import subprocess
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from prosody_core.env import Environment, describe

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

    def as_log(self) -> dict[str, object]:
        return {
            "command": " ".join(self.command),
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


def _run(command: list[str], timeout: int) -> tuple[int | None, str, str, float]:
    """Run FL and capture everything. Never raises.

    A configured path can exist and still not be launchable — the wrong file
    picked in the dialog, a permissions problem, a half-copied install. That
    has to come back as a failed render with a readable reason, not an
    exception the UI reports as "internal".
    """
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        return None, stdout, f"timed out after {timeout}s", time.monotonic() - started
    except OSError as exc:
        return None, "", f"could not start FL Studio: {exc.strerror or exc}", (
            time.monotonic() - started
        )
    return (
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
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
    if code is None:
        message = stderr or "FL Studio did not run"
    elif code != 0:
        message = f"FL Studio exited with {code}"
    elif not produced:
        message = "FL Studio exited cleanly but produced no files"

    return RenderResult(
        ok=success, command=command, exit_code=code, seconds=seconds,
        stdout=stdout, stderr=stderr, outputs=produced, message=message,
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

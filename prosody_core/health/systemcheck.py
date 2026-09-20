"""System Check: every capability, its verdict, and why.

HARDENING P1.4. The purpose is narrow and worth stating: when something does
not work, the user should learn that from Prosody rather than from a build that
quietly produced less than they expected.

Four verdicts, and the distinction between the middle two matters:

* ``PASS`` — checked, and it works.
* ``WARNING`` — works, but something about it will bite later.
* ``UNAVAILABLE`` — does not work *and that is a legitimate configuration*.
  No FL Studio installed means no audio; that is not a fault.
* ``FAIL`` — something that should work does not.

Only FAIL blocks the acceptance gate. Treating UNAVAILABLE as failure would
make "I have not installed FL Studio yet" look like a broken program.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from prosody_core import buildinfo
from prosody_core.env import Environment, describe
from prosody_core.extract import render_fl
from prosody_core.extract import stems as stems_module
from prosody_core.index import db
from prosody_core.workspace import Workspace


class Verdict(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    UNAVAILABLE = "UNAVAILABLE"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Row:
    name: str
    verdict: Verdict
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "verdict": self.verdict.value, "detail": self.detail}


def _writable(directory: Path) -> Row:
    """Actually create and delete a file. Permission bits lie on Windows."""
    name = directory.name or str(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".prosody-write-test"
        probe.write_bytes(b"ok")
        if probe.read_bytes() != b"ok":
            return Row(f"{name} writable", Verdict.FAIL, "a test file did not read back")
        probe.unlink()
    except OSError as exc:
        return Row(f"{name} writable", Verdict.FAIL, f"{directory}: {exc}")
    return Row(f"{name} writable", Verdict.PASS, str(directory))


def _long_paths() -> Row:
    """Whether the OS will accept a path longer than 260 characters.

    A sample under a deep folder inside a OneDrive-synced Documents can exceed
    it easily, and the failure is a confusing "file not found" on a file the
    user can see.
    """
    if os.name != "nt":
        return Row("Long path support", Verdict.PASS, "not a Windows limitation")
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
    except (OSError, ImportError, FileNotFoundError):
        return Row("Long path support", Verdict.WARNING, "could not be determined")
    if int(enabled) == 1:
        return Row("Long path support", Verdict.PASS, "enabled")
    return Row(
        "Long path support",
        Verdict.WARNING,
        "paths over 260 characters may fail; Prosody prefixes its own with \\\\?\\",
    )


def _disk(directory: Path) -> Row:
    try:
        usage = shutil.disk_usage(render_fl._existing_ancestor(directory))
    except OSError as exc:
        return Row("Disk space", Verdict.WARNING, f"could not be checked: {exc}")
    free_gb = usage.free / 1e9
    if free_gb < 1:
        return Row("Disk space", Verdict.FAIL, f"{free_gb:.1f} GB free — too little to render")
    if free_gb < 5:
        return Row("Disk space", Verdict.WARNING, f"{free_gb:.1f} GB free")
    return Row("Disk space", Verdict.PASS, f"{free_gb:.0f} GB free")


def run(workspace: Workspace, env: Environment | None = None) -> dict[str, Any]:
    """Every check, in the order a first run would care about them."""
    env = env or describe(workspace.load_settings())
    rows: list[Row] = []

    # --- what Prosody is ---------------------------------------------------- #
    info = buildinfo.describe()
    if not info.frozen:
        rows.append(Row("Prosody build", Verdict.WARNING, "development build, not a release"))
    elif info.hash_matches is False:
        rows.append(Row(
            "Prosody build", Verdict.WARNING,
            "the core does not match this build's recorded hash",
        ))
    else:
        rows.append(Row(
            "Prosody build", Verdict.PASS,
            f"{info.values.get('prosodyVersion', '?')} "
            f"({str(info.values.get('gitCommit', ''))[:7]})",
        ))

    rows.append(Row("Operating system", Verdict.PASS, f"{platform.system()} {platform.release()}"))

    arch = platform.machine()
    rows.append(Row(
        "Architecture",
        Verdict.PASS if sys.maxsize > 2**32 else Verdict.FAIL,
        arch if sys.maxsize > 2**32 else f"{arch} (32-bit — Prosody needs 64-bit)",
    ))

    rows.append(Row("Core", Verdict.PASS, f"Python {env.python_version}"))

    # --- parsing and writing ------------------------------------------------ #
    rows.append(Row(
        "FLP parser",
        Verdict.PASS,
        f"PyFLP {env.pyflp_version}"
        + (" · compatibility shim active" if env.pyflp_compat_shim else ""),
    ))
    rows.append(_validator_row())
    rows.append(_midi_row())

    # --- FL Studio ---------------------------------------------------------- #
    if env.safe_mode:
        rows.append(Row("FL Studio", Verdict.UNAVAILABLE, "Safe Mode is on"))
    elif env.fl_executable is None:
        rows.append(Row("FL Studio", Verdict.UNAVAILABLE, env.fl_discovery))
    elif not env.fl_architecture_ok:
        rows.append(Row("FL Studio", Verdict.FAIL, f"{env.fl_executable} is {env.fl_architecture}"))
    else:
        rows.append(Row("FL Studio", Verdict.PASS, str(env.fl_executable)))

    can_render, render_reason = render_fl.availability(env)
    rows.append(Row(
        "Render engine",
        Verdict.PASS if can_render else Verdict.UNAVAILABLE,
        render_reason,
    ))

    strategy, stem_reason = stems_module.available_strategy(env)
    rows.append(Row(
        "Stem export",
        Verdict.PASS if strategy else Verdict.UNAVAILABLE,
        f"{strategy.name}: {stem_reason}" if strategy else stem_reason,
    ))

    rows.append(Row(
        "ffmpeg",
        Verdict.PASS if env.ffmpeg else Verdict.UNAVAILABLE,
        str(env.ffmpeg) if env.ffmpeg
        else "not present — not required; FL Studio encodes MP3 itself",
    ))

    # --- storage ------------------------------------------------------------ #
    integrity = db.check_integrity(workspace.db_path)
    if integrity.quarantined:
        rows.append(Row(
            "Library index", Verdict.WARNING,
            f"was corrupt and set aside as {integrity.quarantined.name}; "
            "use Rebuild Library to restore it from your exports",
        ))
    else:
        rows.append(Row("Library index", Verdict.PASS, integrity.detail))

    rows.append(_writable(workspace.export_root()))
    rows.append(_writable(workspace.cache))
    rows.append(_writable(workspace.logs))
    rows.append(_disk(workspace.export_root()))
    rows.append(_long_paths())

    # --- AI ----------------------------------------------------------------- #
    # Ask the planners, rather than guessing from a setting name. Writing this
    # row against a settings key I assumed existed produced a check that would
    # have reported "configured" for a planner that always falls back to rules
    # — which is exactly the kind of lie System Check exists to prevent.
    rows.append(_planner_row())

    counts = {v.value: sum(1 for r in rows if r.verdict is v) for v in Verdict}
    return {
        "rows": [r.as_dict() for r in rows],
        "counts": counts,
        "ok": counts[Verdict.FAIL.value] == 0,
    }


def _validator_row() -> Row:
    try:
        from prosody_core.validate import validator  # noqa: F401
    except ImportError as exc:
        return Row("FLP validator", Verdict.FAIL, f"could not be loaded: {exc}")
    return Row("FLP validator", Verdict.PASS, "structural re-parse after every write")


def _midi_row() -> Row:
    try:
        import mido  # noqa: F401
    except ImportError as exc:
        return Row("MIDI engine", Verdict.FAIL, f"mido could not be loaded: {exc}")
    # mido exposes no __version__; the installed distribution knows.
    try:
        from importlib.metadata import version

        installed = version("mido")
    except Exception:  # noqa: BLE001 - a missing version is cosmetic
        installed = "unknown version"
    return Row("MIDI engine", Verdict.PASS, f"mido {installed}")


def _planner_row() -> Row:
    """What the arrangement planner will actually do, per the planner itself."""
    from prosody_core.ai.planner import PROVIDERS

    usable: list[str] = []
    reasons: list[str] = []
    for name, factory in PROVIDERS.items():
        if name == "rules":
            continue
        ok, why = factory().available()
        (usable if ok else reasons).append(name if ok else f"{name}: {why}")

    if usable:
        return Row("AI planner", Verdict.PASS, ", ".join(usable))
    return Row(
        "AI planner",
        Verdict.UNAVAILABLE,
        "rules-only planning · " + "; ".join(reasons),
    )


def sanitized_report(workspace: Workspace, env: Environment | None = None) -> str:
    """The System Check as text a user can paste into a bug report.

    The user's profile path becomes ``~``. Nothing here ever includes an API
    key: keys are read only to answer "is one configured?", never copied into a
    row (HARDENING P1.4).
    """
    result = run(workspace, env)
    home = str(Path.home())
    lines = ["PROSODY SYSTEM CHECK", ""]
    for row in result["rows"]:
        detail = str(row["detail"]).replace(home, "~")
        lines.append(f"{row['verdict']:<12} {row['name']:<22} {detail}")
    lines.append("")
    counts = result["counts"]
    lines.append(
        f"{counts['PASS']} pass · {counts['WARNING']} warning · "
        f"{counts['UNAVAILABLE']} unavailable · {counts['FAIL']} fail"
    )
    return "\n".join(lines) + "\n"

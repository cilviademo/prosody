"""Stem extraction, behind a strategy interface.

Two strategies, chosen at runtime, with the GUI-automation one isolated so its
assumptions never leak into the rest of the application:

S1 solo-copy   derivative .flp per role with every other channel disabled,
               rendered by the FL command line. Headless and parallel-safe.
S2 gui-export  drives FL's Export dialog with "Split mixer tracks". Needs an
               interactive desktop; only runs with FLPF_GUI=1.

Neither fabricates audio. If no strategy can run, :func:`available_strategy`
returns None and the caller disables the stems option with a reason - it never
copies the master render and calls the copies stems.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from prosody_core.env import Environment, describe
from prosody_core.extract import render_fl
from prosody_core.model.roles import Role
from prosody_core.model.schemas import Analysis, BeatProject
from prosody_core.write.eventstream import Event, read_flp, write_flp

ID_CHANNEL_NEW = 64
ID_CHANNEL_IS_ENABLED = 0


@dataclass
class StemFile:
    role: Role
    path: Path
    bytes: int = 0


@dataclass
class StemResult:
    ok: bool
    strategy: str
    stems: list[StemFile] = field(default_factory=list)
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    log: list[dict[str, object]] = field(default_factory=list)


class StemStrategy(Protocol):
    @property
    def name(self) -> str: ...

    def available(self, env: Environment) -> tuple[bool, str]: ...

    def render(
        self, flp: Path, project: BeatProject, analysis: Analysis, out_dir: Path,
        *, env: Environment,
    ) -> StemResult: ...


def solo_copy(
    source: Path, destination: Path, keep_channels: set[int]
) -> Path:
    """Write a copy of ``source`` with every channel but ``keep_channels`` off.

    Only the per-channel enabled flag is touched; every other byte is copied
    verbatim by the event-stream writer.
    """
    flp = read_flp(source)
    current: int | None = None
    seen_enable_for: set[int] = set()

    events: list[Event] = []
    for event in flp.events:
        if event.id == ID_CHANNEL_NEW:
            current = int.from_bytes(event.payload, "little")
            events.append(event)
            continue
        if event.id == ID_CHANNEL_IS_ENABLED and current is not None:
            on = 1 if current in keep_channels else 0
            events.append(Event(ID_CHANNEL_IS_ENABLED, struct.pack("<B", on)))
            seen_enable_for.add(current)
            continue
        events.append(event)

    # Channels with no explicit enable event need one inserted after New.
    rebuilt: list[Event] = []
    for event in events:
        rebuilt.append(event)
        if event.id == ID_CHANNEL_NEW:
            index = int.from_bytes(event.payload, "little")
            if index not in seen_enable_for:
                on = 1 if index in keep_channels else 0
                rebuilt.append(Event(ID_CHANNEL_IS_ENABLED, struct.pack("<B", on)))

    flp.events = rebuilt
    return write_flp(flp, destination)


class SoloCopyStrategy:
    """S1: one derived project per role, rendered headless by the FL CLI."""

    name = "solo-copy"

    def available(self, env: Environment) -> tuple[bool, str]:
        return render_fl.availability(env)

    def render(
        self, flp: Path, project: BeatProject, analysis: Analysis, out_dir: Path,
        *, env: Environment,
    ) -> StemResult:
        ok, reason = self.available(env)
        if not ok:
            return StemResult(ok=False, strategy=self.name, message=reason)

        by_role: dict[Role, set[int]] = {}
        for assignment in analysis.roles:
            if assignment.channel is None or assignment.role is Role.UNKNOWN:
                continue
            by_role.setdefault(assignment.role, set()).add(assignment.channel)

        if not by_role:
            return StemResult(
                ok=False, strategy=self.name,
                message="no channels were classified confidently enough to split",
            )

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        work = out_dir / "_solo"
        work.mkdir(parents=True, exist_ok=True)

        for role, channels in sorted(by_role.items(), key=lambda kv: kv[0].value):
            solo_copy(flp, work / f"{role.value.capitalize()}.flp", channels)

        result = render_fl.render_folder(work, formats=("wav",), env=env)
        stems = [
            StemFile(
                role=Role(path.stem.lower()) if path.stem.lower() in
                {r.value for r in Role} else Role.UNKNOWN,
                path=path, bytes=path.stat().st_size,
            )
            for path in result.outputs if path.suffix.lower() == ".wav"
        ]

        warnings: list[str] = []
        if stems and len({s.bytes for s in stems}) > 1:
            warnings.append(
                "stem file sizes differ; check they are the same length before "
                "using them for alignment"
            )

        return StemResult(
            ok=result.ok and bool(stems), strategy=self.name, stems=stems,
            message=result.message or ("" if stems else "no stem audio produced"),
            warnings=warnings, log=[result.as_log()],
        )


class GuiExportStrategy:
    """S2: drives FL's Export dialog. Isolated here on purpose.

    Not implemented. It needs an interactive Windows desktop and a click path
    verified against a real FL install; writing it blind would produce
    automation that silently clicks the wrong dialog. The strategy is declared
    so the interface and the selection logic are real, and it reports honestly
    that it cannot run.
    """

    name = "gui-export"

    def available(self, env: Environment) -> tuple[bool, str]:
        if not env.gui_enabled:
            return False, "GUI automation is disabled (set FLPF_GUI=1)"
        if env.fl_executable is None:
            return False, f"FL Studio not found: {env.fl_discovery}"
        return False, (
            "GUI stem export is not implemented: its click path must be verified "
            "against a real FL Studio install first"
        )

    def render(
        self, flp: Path, project: BeatProject, analysis: Analysis, out_dir: Path,
        *, env: Environment,
    ) -> StemResult:
        _, reason = self.available(env)
        return StemResult(ok=False, strategy=self.name, message=reason)


STRATEGIES: tuple[StemStrategy, ...] = (SoloCopyStrategy(), GuiExportStrategy())


def available_strategy(
    env: Environment | None = None,
) -> tuple[StemStrategy | None, str]:
    """The strongest strategy that can run here, and why if none can."""
    env = env or describe()
    if env.safe_mode:
        return None, "Safe Mode is on, so no stem export runs"
    reasons: list[str] = []
    for strategy in STRATEGIES:
        ok, reason = strategy.available(env)
        if ok:
            return strategy, reason
        reasons.append(f"{strategy.name}: {reason}")
    return None, "; ".join(reasons)

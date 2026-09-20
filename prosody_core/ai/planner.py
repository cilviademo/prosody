"""Arrangement planner providers.

The application must arrange without any API key. ``RuleBasedPlanner`` is the
default and always available; the LLM providers rank and annotate the plans the
deterministic engine already produced, and their output is validated against
the same schema and permission level before it can be used.

An LLM never sees audio, a .flp, a file path or a project name. It receives
sanitised counts and enums - see :func:`sanitise` and docs/privacy.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from prosody_core.arrange import profiles
from prosody_core.arrange.planner import build_variants
from prosody_core.model.schemas import (
    Analysis,
    ArrangementPlan,
    BeatProject,
    PermissionLevel,
)


@dataclass(frozen=True)
class PlanRequest:
    project: BeatProject
    analysis: Analysis
    genre: str
    structure: str = "balanced"
    level: PermissionLevel = PermissionLevel.STRUCTURE_ONLY
    variants: int = 3
    seed: int = 1234


class ArrangementPlanner(Protocol):
    @property
    def name(self) -> str: ...

    def available(self) -> tuple[bool, str]: ...

    def plan(self, request: PlanRequest) -> tuple[ArrangementPlan, ...]: ...


def sanitise(request: PlanRequest) -> dict[str, object]:
    """Exactly what may leave the machine: numbers and enum values.

    No file paths, no project or channel names, no audio, no note data.
    """
    return {
        "tempo": request.project.tempo,
        "time_signature": list(request.project.time_signature),
        "length_bars": round(request.project.length_bars, 2),
        "pattern_count": len(request.project.patterns),
        "note_count": request.project.note_count,
        "channel_count": len(request.project.channels),
        "state": request.analysis.state.value,
        "roles": sorted(
            {a.role.value for a in request.analysis.roles if a.is_confident}
        ),
        "genre": request.genre,
        "structure": request.structure,
        "creativity_level": int(request.level),
    }


class RuleBasedPlanner:
    """Deterministic planning from genre profiles. Always available."""

    name = "rules"

    def available(self) -> tuple[bool, str]:
        return True, "deterministic genre rules (no network access)"

    def plan(self, request: PlanRequest) -> tuple[ArrangementPlan, ...]:
        profile = profiles.load(request.genre)
        return build_variants(
            request.project, request.analysis, profile,
            structure=request.structure, level=request.level,
            count=request.variants, seed=request.seed,
        )


class _LLMPlanner:
    """Shared behaviour: rank the deterministic variants, never replace them.

    The LLM is advisory. It cannot introduce an operation, because the plans it
    ranks were produced locally and are re-validated afterwards.
    """

    provider = "llm"
    env_key = ""

    @property
    def name(self) -> str:
        return self.provider

    def available(self) -> tuple[bool, str]:
        import os

        if not os.environ.get(self.env_key):
            return False, f"{self.env_key} is not set"
        return False, (
            f"{self.provider} ranking is not wired up yet; the deterministic "
            "planner is used instead"
        )

    def plan(self, request: PlanRequest) -> tuple[ArrangementPlan, ...]:
        # Falls back rather than failing: arrangement must never depend on a key.
        return RuleBasedPlanner().plan(request)


class ClaudePlanner(_LLMPlanner):
    provider = "claude"
    env_key = "ANTHROPIC_API_KEY"


class OpenAIPlanner(_LLMPlanner):
    provider = "openai"
    env_key = "OPENAI_API_KEY"


PROVIDERS: dict[str, type] = {
    "rules": RuleBasedPlanner,
    "claude": ClaudePlanner,
    "openai": OpenAIPlanner,
}


def get_planner(provider: str = "rules") -> ArrangementPlanner:
    """Return the requested planner, falling back to rules if it cannot run."""
    factory = PROVIDERS.get(provider, RuleBasedPlanner)
    planner = factory()
    ok, _ = planner.available()
    return planner if ok else RuleBasedPlanner()


def log_call(
    log_path: Path, *, model: str, prompt: object, response: object, cost: float = 0.0
) -> None:
    """Append one LLM call to DATA/llm_log.jsonl. Every call, no exceptions."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt": prompt,
        "response": response,
        "cost": cost,
    }
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")

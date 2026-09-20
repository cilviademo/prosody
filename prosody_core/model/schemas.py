"""The only data contract in the application.

Every stage is a pure function over these models; nothing from PyFLP, FL Studio,
an LLM provider or the filesystem layer may appear in a field type. Changing a
model requires an ADR (CLAUDE.md, Conventions).

Units: ticks everywhere internally. Bars appear only at the CLI boundary and
inside ArrangementPlan, which is a human/LLM-facing document.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prosody_core.model.roles import Role

SCHEMA_VERSION = "1.0"


class _Base(BaseModel):
    """Frozen, extra-forbidding base so a typo in a dict literal fails loudly."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class ChannelKind(str, Enum):
    PLUGIN = "plugin"
    SAMPLER = "sampler"
    LAYER = "layer"
    AUTOMATION = "automation"
    UNKNOWN = "unknown"


class ProjectState(str, Enum):
    """How finished the source project looks."""

    EMPTY = "empty"
    LOOP = "loop"
    PARTIAL = "partial"
    ARRANGED = "arranged"
    BROKEN = "broken"


class HealthStatus(str, Enum):
    """Never hide uncertainty: UNKNOWN is a real answer."""

    READY = "READY"
    PARTIAL = "PARTIAL"
    REQUIRES_FREEZE = "REQUIRES_FREEZE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class PermissionLevel(int, Enum):
    STRUCTURE_ONLY = 0
    CONSERVATIVE = 1
    PRODUCER_ASSIST = 2


class ClassificationMethod(str, Enum):
    RULES = "rules"
    LLM = "llm"
    USER = "user"


class SectionType(str, Enum):
    INTRO = "intro"
    VERSE = "verse"
    PRE = "pre"
    HOOK = "hook"
    CHORUS = "chorus"
    BUILD = "build"
    DROP = "drop"
    BRIDGE = "bridge"
    BREAKDOWN = "breakdown"
    OUTRO = "outro"


class JobStatus(str, Enum):
    QUEUED = "queued"
    INSPECTING = "inspecting"
    ANALYZING = "analyzing"
    CLASSIFYING = "classifying"
    PLANNING = "planning"
    ARRANGING = "arranging"
    RENDERING = "rendering"
    VALIDATING = "validating"
    COMPLETE = "complete"
    WARNING = "warning"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# --------------------------------------------------------------------------- #
# Project structure
# --------------------------------------------------------------------------- #

Ticks = Annotated[int, Field(ge=0, description="Position/length in PPQ ticks")]


class Note(_Base):
    channel: int
    position: Ticks
    length: Ticks
    key: int = Field(ge=0, le=131, description="MIDI-ish key number as stored by FL")
    velocity: int = Field(ge=0, le=127)
    pan: int | None = Field(default=None, ge=0, le=127)


class Pattern(_Base):
    index: int = Field(description="FL's 1-based internal pattern id (iid)")
    name: str | None = None
    length_ticks: Ticks = 0
    notes: tuple[Note, ...] = ()

    @property
    def note_count(self) -> int:
        return len(self.notes)


class Channel(_Base):
    index: int
    name: str | None = None
    kind: ChannelKind = ChannelKind.UNKNOWN
    plugin: str | None = None
    sample_path: str | None = None
    mixer_track: int | None = None
    enabled: bool = True


class MixerInsert(_Base):
    index: int
    name: str | None = None
    effects: tuple[str, ...] = ()
    routes_to: tuple[int, ...] = ()


class PlaylistClip(_Base):
    """One item on a playlist track. Either a pattern clip or a channel clip."""

    track: int
    kind: Literal["pattern", "channel"] = "pattern"
    pattern: int | None = None
    channel: int | None = None
    start_ticks: Ticks = 0
    length_ticks: Ticks = 0

    @model_validator(mode="after")
    def _target_matches_kind(self) -> PlaylistClip:
        if self.kind == "pattern" and self.pattern is None:
            raise ValueError("pattern clip requires a pattern index")
        if self.kind == "channel" and self.channel is None:
            raise ValueError("channel clip requires a channel index")
        return self


class PlaylistTrack(_Base):
    index: int
    name: str | None = None
    clip_count: int = 0


class Marker(_Base):
    position_ticks: Ticks
    name: str | None = None


class Arrangement(_Base):
    index: int
    name: str | None = None
    tracks: tuple[PlaylistTrack, ...] = ()
    clips: tuple[PlaylistClip, ...] = ()
    markers: tuple[Marker, ...] = ()


class SampleRef(_Base):
    path: str
    found: bool
    used_by_channels: tuple[int, ...] = ()


class PluginRef(_Base):
    name: str
    used_by_channels: tuple[int, ...] = ()


class KeyGuess(_Base):
    root: str
    mode: Literal["major", "minor"]
    confidence: float = Field(ge=0.0, le=1.0)


class ParseWarning(_Base):
    """Something the parser could not do, surfaced rather than swallowed."""

    code: str
    message: str
    severity: Severity = Severity.WARNING


class BeatProject(_Base):
    """Normalised, backend-independent view of one .flp file."""

    schema_version: str = SCHEMA_VERSION
    id: str = Field(description="sha256 of the source .flp bytes")
    source_path: str
    source_bytes: int = 0
    parsed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    backend: str = Field(description="Parser backend name and version")

    fl_version: str | None = None
    fl_build: int | None = None
    format: int | None = None
    tempo: float | None = Field(default=None, gt=0)
    ppq: int = 96
    time_signature: tuple[int, int] = (4, 4)
    length_ticks: Ticks = 0
    key_guess: KeyGuess | None = None
    title: str | None = None

    channels: tuple[Channel, ...] = ()
    patterns: tuple[Pattern, ...] = ()
    mixer: tuple[MixerInsert, ...] = ()
    arrangements: tuple[Arrangement, ...] = ()
    samples: tuple[SampleRef, ...] = ()
    plugins: tuple[PluginRef, ...] = ()
    unknown_event_ids: tuple[int, ...] = Field(
        default=(),
        description="Event ids PyFLP had no model for. Preserved, never dropped.",
    )
    parse_warnings: tuple[ParseWarning, ...] = ()

    @property
    def note_count(self) -> int:
        return sum(p.note_count for p in self.patterns)

    @property
    def length_bars(self) -> float:
        """Project length in bars. 0.0 when tempo/ppq cannot be trusted."""
        beats_per_bar = self.time_signature[0]
        if not self.ppq or not beats_per_bar:
            return 0.0
        return self.length_ticks / (self.ppq * beats_per_bar)

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock length implied by tempo. None when tempo is unknown."""
        if not self.tempo or not self.ppq:
            return None
        return (self.length_ticks / self.ppq) * (60.0 / self.tempo)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


class MissingAsset(_Base):
    kind: Literal["sample", "plugin"]
    identifier: str
    detail: str | None = None


class HealthCheck(_Base):
    """One named observation. `ok=None` means genuinely undetermined."""

    name: str
    ok: bool | None
    detail: str


class HealthReport(_Base):
    schema_version: str = SCHEMA_VERSION
    project_id: str
    status: HealthStatus = HealthStatus.UNKNOWN
    checks: tuple[HealthCheck, ...] = ()
    samples_found: int = 0
    samples_missing: int = 0
    missing_assets: tuple[MissingAsset, ...] = ()
    render_test: Literal["pass", "fail", "skipped"] = "skipped"
    recommended_mode: Literal["native", "stem", "none"] = "none"
    notes: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Analysis / classification
# --------------------------------------------------------------------------- #


class RoleAssignment(_Base):
    """A role guess. `confidence` is never rounded up into certainty."""

    pattern: int | None = None
    channel: int | None = None
    role: Role = Role.UNKNOWN
    confidence: float = Field(ge=0.0, le=1.0)
    method: ClassificationMethod = ClassificationMethod.RULES
    sources: tuple[str, ...] = Field(
        default=(), description="Which signals contributed, e.g. channel_name"
    )

    @property
    def is_confident(self) -> bool:
        return self.confidence >= CONFIDENCE_THRESHOLD


#: Below this, a role guess must not be treated as fact (SPEC section 10).
CONFIDENCE_THRESHOLD = 0.70


class Analysis(_Base):
    schema_version: str = SCHEMA_VERSION
    project_id: str
    state: ProjectState = ProjectState.EMPTY
    roles: tuple[RoleAssignment, ...] = ()
    completion_estimate: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def confident_roles(self) -> tuple[RoleAssignment, ...]:
        return tuple(r for r in self.roles if r.is_confident)


# --------------------------------------------------------------------------- #
# Arrangement (contract only - no planner ships in this phase)
# --------------------------------------------------------------------------- #

#: Which playlist operations each permission level may express. Enforced by
#: ArrangementPlan's validator, not by prompt text (SPEC section 2, rule 4).
ALLOWED_OPS_BY_LEVEL: dict[PermissionLevel, frozenset[str]] = {
    PermissionLevel.STRUCTURE_ONLY: frozenset(
        {"tile", "place", "mute", "duplicate_pattern", "dropout", "marker"}
    ),
    PermissionLevel.CONSERVATIVE: frozenset(
        {
            "tile", "place", "mute", "duplicate_pattern", "dropout", "marker",
            "remove_notes", "scale_velocity", "octave_shift", "halve_pattern",
            "double_pattern", "fill_from_existing",
        }
    ),
    PermissionLevel.PRODUCER_ASSIST: frozenset(
        {
            "tile", "place", "mute", "duplicate_pattern", "dropout", "marker",
            "remove_notes", "scale_velocity", "octave_shift", "halve_pattern",
            "double_pattern", "fill_from_existing",
            "generate_counter_melody", "generate_transition", "generate_bass_variation",
        }
    ),
}


class PlaylistOp(_Base):
    """A single deterministic mutation. The engine executes only these."""

    op: str
    role: Role | None = None
    pattern: int | None = None
    track: int | None = None
    start_bar: int | None = Field(default=None, ge=1)
    bars: int | None = Field(default=None, ge=1)


class Section(_Base):
    name: SectionType
    start_bar: int = Field(ge=1)
    bars: int = Field(ge=1)
    energy: float = Field(ge=0.0, le=1.0)
    active_roles: tuple[Role, ...] = ()
    dropout_bars: int = Field(default=0, ge=0)


class ArrangementPlan(_Base):
    schema_version: str = SCHEMA_VERSION
    variant: str = "A"
    genre: str
    structure: str = "balanced"
    level: PermissionLevel = PermissionLevel.STRUCTURE_ONLY
    seed: int = 0
    source_project_id: str
    tempo: float = Field(gt=0)
    total_bars: int = Field(ge=1)
    sections: tuple[Section, ...] = ()
    ops: tuple[PlaylistOp, ...] = ()
    llm_notes: str | None = None

    @model_validator(mode="after")
    def _ops_within_permission_level(self) -> ArrangementPlan:
        allowed = ALLOWED_OPS_BY_LEVEL[self.level]
        offending = sorted({op.op for op in self.ops if op.op not in allowed})
        if offending:
            raise ValueError(
                f"operations {offending} exceed permission level {self.level.value}"
            )
        return self

    @model_validator(mode="after")
    def _sections_are_contiguous(self) -> ArrangementPlan:
        cursor = 1
        for section in self.sections:
            if section.start_bar != cursor:
                raise ValueError(
                    f"section {section.name.value} starts at bar {section.start_bar}, "
                    f"expected {cursor}"
                )
            cursor += section.bars
        return self


class EntryRule(_Base):
    """When a role is first allowed to appear, as a data rule rather than code."""

    role: Role
    not_before: SectionType | None = None
    absent_from: tuple[SectionType, ...] = ()


class GenreProfile(_Base):
    genre: str
    label: str = ""
    grammar: dict[str, tuple[str, ...]]
    energy: dict[SectionType, float]
    role_weights: dict[Role, float]
    #: Roles offered in priority order while filling a section to its density.
    role_priority: tuple[Role, ...] = ()
    entry_rules: tuple[EntryRule, ...] = ()
    #: Sections after which a 1-2 bar drum dropout reads as a transition.
    dropout_before: tuple[SectionType, ...] = ()
    rules: tuple[str, ...] = ()

    def energy_for(self, section: SectionType) -> float:
        return self.energy.get(section, 0.5)


# --------------------------------------------------------------------------- #
# Execution bookkeeping
# --------------------------------------------------------------------------- #


class ValidationResult(_Base):
    schema_version: str = SCHEMA_VERSION
    project_id: str
    passed: bool
    checks: tuple[HealthCheck, ...] = ()


class Job(_Base):
    id: str
    source_path: str
    status: JobStatus = JobStatus.QUEUED
    message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Build outputs
# --------------------------------------------------------------------------- #


class OutputTier(str, Enum):
    """How complete the generated project is. Both tiers are supported results.

    NATIVE is the goal: an editable derivative .flp. PACK is the documented
    fallback when a project cannot safely be rewritten - it is not an error.
    """

    NATIVE = "native"
    PACK = "pack"
    NONE = "none"


class ArtifactKind(str, Enum):
    FLP = "flp"
    WAV = "wav"
    MP3 = "mp3"
    MIDI = "midi"
    STEM = "stem"
    ZIP = "zip"
    JSON = "json"
    REPORT = "report"


class Artifact(_Base):
    """One file this application produced."""

    kind: ArtifactKind
    path: str
    label: str
    bytes: int = 0


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageResult(_Base):
    """One visible step of a build, with an honest outcome."""

    name: str
    status: StageStatus
    detail: str = ""
    artifacts: tuple[Artifact, ...] = ()


class BuildResult(_Base):
    schema_version: str = SCHEMA_VERSION
    project_id: str
    out_dir: str
    tier: OutputTier = OutputTier.NONE
    stages: tuple[StageResult, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    flp_path: str | None = None
    preview_wav: str | None = None
    preview_mp3: str | None = None
    source_hash_verified: bool = False
    message: str = ""

    @property
    def ok(self) -> bool:
        return not any(s.status is StageStatus.FAILED for s in self.stages)


class LibraryEntry(_Base):
    """One row of the Library view."""

    project_id: str
    name: str
    source_path: str
    tempo: float | None = None
    key: str | None = None
    length_bars: float = 0.0
    genre: str | None = None
    status: str = "Starter"
    health: HealthStatus = HealthStatus.UNKNOWN
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    out_dir: str | None = None

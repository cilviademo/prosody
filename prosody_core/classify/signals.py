"""Musical-signal role classification.

The name-only hinter in ``rules.py`` is the weakest of several signals. This
module combines everything available - name, plugin, sample filename, mixer
track name, pitch range, polyphony, note duration, note density and rhythmic
placement - into one weighted vote per channel.

Design notes:

* Signals *vote*; they do not override each other. A channel called "Kick" that
  plays sustained chords in the treble is genuinely ambiguous, and the result
  should say so rather than trust whichever rule ran last.
* Confidence is the winning score relative to the total vote, damped by how
  little evidence there was. Nothing reaches certainty from one weak signal.
* FL's key numbering is used throughout: 60 is C5 in FL, and the General MIDI
  drum map does not apply, so pitch is used as a *range* signal only.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass

from prosody_core.classify.rules import role_from_name
from prosody_core.model.roles import Role
from prosody_core.model.schemas import (
    Analysis,
    BeatProject,
    Channel,
    ChannelKind,
    ClassificationMethod,
    Note,
    ProjectState,
    RoleAssignment,
)

#: Weight of each signal in the vote. Names are strong because producers do
#: label their drums; musical shape is strong because names are often absent.
W_NAME = 3.0
W_SAMPLE = 2.5
W_PLUGIN = 1.0
W_MIXER = 1.5
W_PITCH = 2.0
W_POLYPHONY = 2.0
W_DURATION = 1.5
W_DENSITY = 1.5

#: FL key numbers. 60 == C5 in FL's display.
C2, C3, C4, C5, C6, C7 = 24, 36, 48, 60, 72, 84


@dataclass(frozen=True)
class ChannelFeatures:
    """Measured properties of one channel's note content."""

    note_count: int
    pitch_min: int | None
    pitch_max: int | None
    pitch_median: float | None
    max_simultaneous: int
    mean_length_ticks: float
    notes_per_bar: float
    distinct_pitches: int
    on_beat_ratio: float

    @property
    def has_notes(self) -> bool:
        return self.note_count > 0

    @property
    def pitch_span(self) -> int:
        if self.pitch_min is None or self.pitch_max is None:
            return 0
        return self.pitch_max - self.pitch_min


def measure(notes: list[Note], ppq: int, beats_per_bar: int) -> ChannelFeatures:
    """Reduce a channel's notes to the features the classifier votes on."""
    if not notes:
        return ChannelFeatures(0, None, None, None, 0, 0.0, 0.0, 0, 0.0)

    pitches = sorted(n.key for n in notes)
    median = pitches[len(pitches) // 2]

    # Maximum simultaneous notes, by sweeping note starts and ends.
    events: list[tuple[int, int]] = []
    for note in notes:
        events.append((note.position, 1))
        events.append((note.position + max(note.length, 1), -1))
    events.sort()
    current = peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)

    span_ticks = max(
        max(n.position + n.length for n in notes) - min(n.position for n in notes), 1
    )
    bars = max(span_ticks / (ppq * beats_per_bar), 1e-6)

    beat_ticks = max(ppq, 1)
    on_beat = sum(1 for n in notes if n.position % beat_ticks == 0)

    return ChannelFeatures(
        note_count=len(notes),
        pitch_min=pitches[0],
        pitch_max=pitches[-1],
        pitch_median=float(median),
        max_simultaneous=peak,
        mean_length_ticks=sum(n.length for n in notes) / len(notes),
        notes_per_bar=len(notes) / bars,
        distinct_pitches=len(set(pitches)),
        on_beat_ratio=on_beat / len(notes),
    )


class _Ballot:
    """Accumulates weighted votes and the sources that cast them."""

    def __init__(self) -> None:
        self.scores: defaultdict[Role, float] = defaultdict(float)
        self.sources: set[str] = set()

    def cast(self, role: Role, weight: float, source: str) -> None:
        if role is Role.UNKNOWN or weight <= 0:
            return
        self.scores[role] += weight
        self.sources.add(source)

    def spread(self, roles: tuple[Role, ...], weight: float, source: str) -> None:
        """Split one signal's weight across equally plausible roles."""
        if not roles:
            return
        for role in roles:
            self.cast(role, weight / len(roles), source)

    def result(self) -> tuple[Role, float, tuple[str, ...]]:
        if not self.scores:
            return Role.UNKNOWN, 0.0, ()
        ranked = sorted(self.scores.items(), key=lambda kv: kv[1], reverse=True)
        role, top = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

        # Confidence is how decisively the winner beats its nearest rival, not
        # how it compares to the sum of every alternative. Spread votes widen
        # the field without making the leader less likely, so a share-of-total
        # measure would punish exactly the channels we identified best.
        margin = top / (top + runner_up) if (top + runner_up) else 0.0

        # Damped by how much evidence there was: one weak signal agreeing with
        # itself is not four signals agreeing.
        evidence = 1.0 - math.exp(-top / 2.5)
        confidence = round(min(0.97, margin * evidence), 3)
        return role, confidence, tuple(sorted(self.sources))


_SAMPLE_HINTS: tuple[tuple[str, Role], ...] = (
    ("kick", Role.KICK), ("bd", Role.KICK), ("808", Role.BASS),
    ("snare", Role.SNARE), ("clap", Role.SNARE), ("rim", Role.SNARE),
    ("hat", Role.HATS), ("hh", Role.HATS),
    ("crash", Role.PERC), ("ride", Role.PERC), ("tom", Role.PERC),
    ("shaker", Role.PERC), ("perc", Role.PERC), ("conga", Role.PERC),
    ("vox", Role.VOCAL), ("vocal", Role.VOCAL),
    ("riser", Role.FX), ("sweep", Role.FX), ("impact", Role.FX), ("fx", Role.FX),
    ("bass", Role.BASS), ("sub", Role.BASS),
    ("piano", Role.CHORDS), ("rhodes", Role.CHORDS), ("pad", Role.CHORDS),
    ("string", Role.CHORDS), ("organ", Role.CHORDS),
    ("lead", Role.MELODY), ("pluck", Role.MELODY), ("bell", Role.MELODY),
    ("arp", Role.MELODY), ("flute", Role.MELODY), ("guitar", Role.MELODY),
)

_PLUGIN_HINTS: tuple[tuple[str, Role], ...] = (
    ("fpc", Role.PERC), ("drumaxx", Role.PERC), ("drumpad", Role.PERC),
    ("slicex", Role.MELODY), ("fruity slicer", Role.MELODY),
    ("gms", Role.MELODY), ("3x osc", Role.MELODY),
    ("sytrus", Role.MELODY), ("harmor", Role.MELODY), ("serum", Role.MELODY),
    ("massive", Role.BASS), ("sub bass", Role.BASS),
    ("keys", Role.CHORDS), ("piano", Role.CHORDS), ("electric", Role.CHORDS),
    ("omnisphere", Role.CHORDS), ("kontakt", Role.CHORDS),
)


def _vote_text(ballot: _Ballot, text: str | None, weight: float, source: str,
               hints: tuple[tuple[str, Role], ...]) -> None:
    if not text:
        return
    lowered = text.lower()
    for needle, role in hints:
        if needle in lowered:
            ballot.cast(role, weight, source)
            return


def _vote_pitch(ballot: _Ballot, f: ChannelFeatures) -> None:
    """Register is a strong hint about function, and a weak one about identity."""
    if f.pitch_median is None:
        return

    # A single repeated pitch is a trigger, not a register: a kick sampled at
    # C5 says nothing about function. Vote percussion and skip the range vote,
    # which would otherwise drag every one-shot toward melody.
    if f.distinct_pitches == 1 and f.note_count >= 4:
        ballot.spread((Role.KICK, Role.SNARE, Role.HATS, Role.PERC),
                      W_PITCH * 1.5, "single_pitch")
        return

    median = f.pitch_median

    if median < C3:
        # Deep register: bass, or a kick sample triggered low.
        ballot.spread((Role.BASS, Role.KICK), W_PITCH, "pitch_range")
    elif median < C4:
        ballot.spread((Role.BASS, Role.CHORDS), W_PITCH * 0.8, "pitch_range")
    elif median < C6:
        ballot.spread((Role.CHORDS, Role.MELODY, Role.VOCAL), W_PITCH * 0.6, "pitch_range")
    else:
        ballot.spread((Role.MELODY, Role.HATS, Role.FX), W_PITCH * 0.8, "pitch_range")


def _vote_polyphony(ballot: _Ballot, f: ChannelFeatures) -> None:
    if not f.has_notes:
        return
    if f.max_simultaneous >= 3:
        ballot.cast(Role.CHORDS, W_POLYPHONY, "polyphony")
    elif f.max_simultaneous == 2:
        ballot.spread((Role.CHORDS, Role.MELODY), W_POLYPHONY * 0.5, "polyphony")
    else:
        ballot.spread((Role.MELODY, Role.BASS, Role.KICK, Role.SNARE, Role.HATS),
                      W_POLYPHONY * 0.4, "polyphony")


def _vote_duration(ballot: _Ballot, f: ChannelFeatures, ppq: int) -> None:
    if not f.has_notes or not ppq:
        return
    beats = f.mean_length_ticks / ppq
    if beats < 0.2:
        ballot.spread((Role.HATS, Role.PERC, Role.KICK, Role.SNARE),
                      W_DURATION, "note_duration")
    elif beats >= 2.0:
        ballot.spread((Role.CHORDS, Role.BASS), W_DURATION, "note_duration")
    elif beats >= 1.0:
        ballot.spread((Role.CHORDS, Role.MELODY, Role.BASS),
                      W_DURATION * 0.6, "note_duration")


def _vote_density(ballot: _Ballot, f: ChannelFeatures) -> None:
    if not f.has_notes:
        return
    if f.notes_per_bar >= 12:
        ballot.spread((Role.HATS, Role.PERC), W_DENSITY, "note_density")
    elif f.notes_per_bar <= 2:
        ballot.spread((Role.CHORDS, Role.BASS, Role.FX), W_DENSITY * 0.6, "note_density")

    # Sparse and dead-on the beat, low register: reads as a kick pattern.
    if f.on_beat_ratio > 0.9 and f.notes_per_bar <= 6 and (f.pitch_median or 99) < C4:
        ballot.cast(Role.KICK, W_DENSITY, "on_beat")


def _notes_by_channel(project: BeatProject) -> dict[int, list[Note]]:
    grouped: dict[int, list[Note]] = defaultdict(list)
    for pattern in project.patterns:
        for note in pattern.notes:
            grouped[note.channel].append(note)
    return grouped


def classify_channel(
    channel: Channel,
    notes: list[Note],
    *,
    ppq: int,
    beats_per_bar: int,
    mixer_name: str | None = None,
) -> RoleAssignment:
    """Combine every available signal into one role assignment."""
    ballot = _Ballot()
    features = measure(notes, ppq, beats_per_bar)

    role, _, _ = role_from_name(channel.name)
    ballot.cast(role, W_NAME, "channel_name")

    if channel.sample_path:
        stem = re.split(r"[\\/]", channel.sample_path)[-1]
        _vote_text(ballot, stem, W_SAMPLE, "sample_filename", _SAMPLE_HINTS)
    _vote_text(ballot, channel.plugin, W_PLUGIN, "plugin_name", _PLUGIN_HINTS)

    mixer_role, _, _ = role_from_name(mixer_name)
    ballot.cast(mixer_role, W_MIXER, "mixer_track_name")

    if features.has_notes:
        _vote_pitch(ballot, features)
        _vote_polyphony(ballot, features)
        _vote_duration(ballot, features, ppq)
        _vote_density(ballot, features)

    # An automation channel is never a musical role.
    if channel.kind is ChannelKind.AUTOMATION:
        return RoleAssignment(
            channel=channel.index, role=Role.UNKNOWN, confidence=0.0,
            method=ClassificationMethod.RULES, sources=("automation_channel",),
        )

    winner, confidence, sources = ballot.result()
    return RoleAssignment(
        channel=channel.index, role=winner, confidence=confidence,
        method=ClassificationMethod.RULES, sources=sources,
    )


def classify_project(project: BeatProject) -> tuple[RoleAssignment, ...]:
    """One assignment per channel, in channel order."""
    grouped = _notes_by_channel(project)
    mixer_names = {insert.index: insert.name for insert in project.mixer}
    beats_per_bar = project.time_signature[0] or 4
    return tuple(
        classify_channel(
            channel,
            grouped.get(channel.index, []),
            ppq=project.ppq,
            beats_per_bar=beats_per_bar,
            mixer_name=mixer_names.get(channel.mixer_track or -1),
        )
        for channel in project.channels
    )


def analyse_project(project: BeatProject, state: ProjectState) -> Analysis:
    """Full analysis using every signal. Supersedes rules.analyse."""
    roles = classify_project(project)
    identified = sum(1 for r in roles if r.role is not Role.UNKNOWN)
    coverage = identified / len(roles) if roles else 0.0

    # A rough "how finished does this look" number: role coverage, whether the
    # core kit is present, and whether anything is on the playlist.
    present = {r.role for r in roles if r.is_confident}
    core = {Role.KICK, Role.SNARE, Role.BASS, Role.CHORDS}
    core_share = len(present & core) / len(core)
    arranged = 1.0 if any(a.clips for a in project.arrangements) else 0.0
    completion = round(0.5 * coverage + 0.3 * core_share + 0.2 * arranged, 3)

    return Analysis(
        project_id=project.id,
        state=state,
        roles=roles,
        completion_estimate=min(completion, 1.0),
    )


def roles_present(analysis: Analysis) -> dict[Role, list[int]]:
    """Confident role -> the channel indices that carry it."""
    out: dict[Role, list[int]] = defaultdict(list)
    for assignment in analysis.roles:
        if assignment.is_confident and assignment.channel is not None:
            out[assignment.role].append(assignment.channel)
    return dict(out)

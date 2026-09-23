"""Ground-truth fixtures (ARCHITECTURE_NOTES item 5), synthetic for now.

Three projects made of the same material:

* **A** — a 4-bar loop: drums, bass, chords, melody, known routing. The shape
  of ``loop_test.flp``, which replaces this the day it parses on the PC.
* **B** — a finished 64-bar arrangement of A's patterns. Reference only: it
  is never fed to the planner, because a planner that has seen the answer
  proves nothing.
* **B_unfinished** — B with the arrangement removed. What the planner is
  asked to finish; the test compares its structure's length with B's.

Real files saved by FL Studio are still owed; until then these are honest
about being synthetic (ADR-0003).
"""

from __future__ import annotations

from tests.fixtures.flp_builder import (
    TYPE_NATIVE,
    ChannelSpec,
    ClipSpec,
    FlpSpec,
    NoteSpec,
    PatternSpec,
)

PPQ = 96
BAR = 4 * PPQ

#: pattern iid → (name, channel, notes for one 4-bar pattern)
_MATERIAL = {
    1: ("Drums", 0, tuple(NoteSpec(i * PPQ, PPQ // 4, 60, 110, 0) for i in range(16))),
    2: ("Bass", 1, tuple(NoteSpec(b * BAR, BAR // 2, 36 + (b % 2) * 3, 100, 1) for b in range(4))),
    3: ("Chords", 2, tuple(
        NoteSpec(b * BAR, BAR, k, 90, 2) for b in range(4) for k in (60, 63, 67))),
    4: ("Melody", 3, tuple(NoteSpec(i * PPQ // 2, PPQ // 2, 72 + (i % 5), 95, 3) for i in range(32))),
}

_CHANNELS = [
    ChannelSpec("Kick Kit", 1, "D:\\GT\\kit.wav"),
    ChannelSpec("Sub Bass", 2, kind=TYPE_NATIVE),
    ChannelSpec("Rhodes Chords", 3, kind=TYPE_NATIVE),
    ChannelSpec("Lead Melody", 4, kind=TYPE_NATIVE),
]

#: The finished arrangement: (section, bars, patterns that play). 64 bars.
_B_STRUCTURE = [
    ("intro", 8, (3,)), ("verse", 16, (1, 2, 3)), ("chorus", 16, (1, 2, 3, 4)),
    ("verse", 8, (1, 2, 3)), ("chorus", 8, (1, 2, 3, 4)), ("outro", 8, (3, 4)),
]
B_TOTAL_BARS = sum(bars for _, bars, _ in _B_STRUCTURE)


def _patterns() -> list[PatternSpec]:
    return [PatternSpec(iid=i, name=n, notes=notes) for i, (n, _, notes) in _MATERIAL.items()]


def ground_truth_a() -> FlpSpec:
    """The 4-bar loop, played once."""
    return FlpSpec(
        title="Ground Truth A", tempo=96.0, ppq=PPQ, channels=list(_CHANNELS),
        patterns=_patterns(),
        clips=[ClipSpec(pattern_iid=i, track=i - 1, start_ticks=0, length_ticks=4 * BAR)
               for i in _MATERIAL],
        track_names=["Drums", "Bass", "Chords", "Melody"],
    )


def ground_truth_b() -> FlpSpec:
    """The finished 64-bar arrangement of A's material. Reference only."""
    clips: list[ClipSpec] = []
    bar = 0
    for _name, bars, active in _B_STRUCTURE:
        for rep in range(bars // 4):
            for iid in active:
                clips.append(ClipSpec(pattern_iid=iid, track=iid - 1,
                                      start_ticks=(bar + rep * 4) * BAR, length_ticks=4 * BAR))
        bar += bars
    return FlpSpec(
        title="Ground Truth B", tempo=96.0, ppq=PPQ, channels=list(_CHANNELS),
        patterns=_patterns(), clips=clips,
        track_names=["Drums", "Bass", "Chords", "Melody"],
    )


def ground_truth_b_unfinished() -> FlpSpec:
    """B with the arrangement removed: the same patterns, nothing placed."""
    spec = ground_truth_b()
    spec.title = "Ground Truth B (unfinished)"
    spec.clips = []
    return spec

"""Richer synthetic projects for the arrangement and writer tests.

``full_kit`` is the shape the product is built for: a four-bar starter with
drums, bass, chords and melody on separate patterns.
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
BAR = PPQ * 4


def full_kit(tempo: float = 142.0) -> FlpSpec:
    """Four-bar starter: kick, snare, hats, 808, chords, melody."""
    return FlpSpec(
        title="Starfall",
        tempo=tempo,
        ppq=PPQ,
        channels=[
            ChannelSpec("Kick", 1, "D:\\Drums\\Kick_01.wav"),
            ChannelSpec("Snare", 2, "D:\\Drums\\Snare21.wav"),
            ChannelSpec("ClosedHat", 3, "D:\\Drums\\HH_closed.wav"),
            ChannelSpec("808 Bass", 4, kind=TYPE_NATIVE),
            ChannelSpec("Rhodes Chords", 5, kind=TYPE_NATIVE),
            ChannelSpec("Lead Melody", 6, kind=TYPE_NATIVE),
        ],
        patterns=[
            PatternSpec(1, "Kick", tuple(
                NoteSpec(i * PPQ, PPQ // 4, 60, 110, 0) for i in range(16))),
            PatternSpec(2, "Snare", tuple(
                NoteSpec(PPQ * (2 * i + 1), PPQ // 4, 60, 100, 1) for i in range(8))),
            PatternSpec(3, "Hats", tuple(
                NoteSpec(i * PPQ // 2, PPQ // 8, 60, 80, 2) for i in range(32))),
            PatternSpec(4, "808", tuple(
                NoteSpec(b * PPQ * 2, PPQ * 2, 26 + b % 3, 120, 3) for b in range(8))),
            PatternSpec(5, "Chords", tuple(
                NoteSpec(b * BAR, BAR, k, 90, 4)
                for b in range(4) for k in (48, 52, 55))),
            PatternSpec(6, "Melody", tuple(
                NoteSpec(i * PPQ // 2, PPQ // 2, 72 + (i % 5), 95, 5)
                for i in range(32))),
        ],
        track_names=["Kick", "Snare", "Hats", "808", "Chords", "Melody"],
        mixer_names=["Master", "Kick", "Snare", "Hats", "808", "Keys", "Lead"],
    )


def melody_only() -> FlpSpec:
    """A project with no drums at all - the engine must not invent any."""
    return FlpSpec(
        title="Sketch",
        tempo=90.0,
        ppq=PPQ,
        channels=[ChannelSpec("Rhodes Chords", 1, kind=TYPE_NATIVE)],
        patterns=[
            PatternSpec(1, "Chords", tuple(
                NoteSpec(b * BAR, BAR, k, 90, 0)
                for b in range(4) for k in (48, 52, 55))),
        ],
        track_names=["Chords"],
        mixer_names=["Master", "Keys"],
    )


def no_notes() -> FlpSpec:
    """Channels but no note content: arranging must refuse, extracting must not."""
    spec = full_kit()
    spec.patterns = [PatternSpec(1, "Empty", ())]
    return spec


def already_arranged() -> FlpSpec:
    spec = full_kit()
    spec.title = "Arranged"
    spec.clips = [
        ClipSpec(pattern_iid=p, track=t, start_ticks=BAR * 4 * i, length_ticks=BAR * 4)
        for i in range(4)
        for t, p in enumerate((1, 5), start=0)
    ]
    return spec


def fl2026_loop() -> FlpSpec:
    """A 4-bar loop shaped like one saved by FL Studio 2026 on the studio PC.

    Version string in the 2026 line, a build number FL 2026 would write, and
    the two channel-rack display groups the real file carried. Whatever else
    FL 2026 adds is unknown until the event inventory of the real file is
    pasted back; this fixture proves the reader survives what is known.
    """
    ppq = PPQ
    return FlpSpec(
        title="Loop Starter",
        fl_version="2026.1.0.4321",
        fl_build=5121,
        tempo=128.0,
        ppq=ppq,
        display_groups=["Unsorted", "Loop Starter #1"],
        channels=[
            ChannelSpec("Kick", 1, "D:\\Drums\\Kick.wav"),
            ChannelSpec("Keys", 2, kind=TYPE_NATIVE),
        ],
        patterns=[
            PatternSpec(iid=1, name="Drums", notes=tuple(
                NoteSpec(position=i * ppq, length=ppq // 2, key=60, velocity=100, channel=0)
                for i in range(16)
            )),
            PatternSpec(iid=2, name="Chords", notes=tuple(
                NoteSpec(position=bar * 4 * ppq, length=4 * ppq, key=key, velocity=90, channel=1)
                for bar in range(4) for key in (60, 64, 67)
            )),
        ],
        clips=[
            ClipSpec(pattern_iid=1, track=0, start_ticks=0, length_ticks=16 * ppq),
            ClipSpec(pattern_iid=2, track=1, start_ticks=0, length_ticks=16 * ppq),
        ],
        track_names=["Drums", "Keys"],
    )


def audio_clip_session() -> FlpSpec:
    """An arrangement of audio clips and no patterns — the Tony x Eddie shape.

    Playlist clips that refer to channels rather than patterns, so there is
    nothing to arrange from, and the interface has to say why.
    """
    return FlpSpec(
        title="Audio Session",
        tempo=156.0,
        channels=[
            ChannelSpec("Vocal take 1", 1, "D:\\Takes\\vox1.wav"),
            ChannelSpec("Guitar DI", 2, "D:\\Takes\\gtr.wav"),
        ],
        clips=[
            ClipSpec(pattern_iid=0, track=0, start_ticks=0, length_ticks=16 * PPQ, channel_iid=0),
            ClipSpec(pattern_iid=0, track=1, start_ticks=0, length_ticks=16 * PPQ, channel_iid=1),
        ],
        track_names=["Vox", "Gtr"],
    )

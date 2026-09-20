"""Minimal synthetic .flp writer, for tests that must not ship real projects.

The corpus of real FL projects is personal and copyrighted, so it stays out of
git (SPEC.md section 8; product brief section 16). This module emits *real*
FLP binaries - byte-for-byte the FLhd/FLdt container FL Studio writes - so the
parser is exercised against the actual format rather than a mock.

It is a **test fixture, not a project writer**. It covers only the events the
reader needs. It is deliberately not in ``prosody_core/``: nothing in the
application may depend on it, and it must never be pointed at a real project.

Format reference (verified against PyFLP 2.2.1 during Phase 0):
  header  "FLhd" | u32 size=6 | i16 format | u16 channel_count | u16 ppq
  data    "FLdt" | u32 size | events...
  event   u8 id | payload, where the id selects the payload width:
            id <  64  ->  1 byte
            id < 128  ->  2 bytes
            id < 192  ->  4 bytes
            id >= 192 ->  varint length + bytes
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

# Event ids, from PyFLP's enums.
FL_VERSION = 199
FL_BUILD = 159
TEMPO = 156
TITLE = 194
TIMESIG_NUM = 17
TIMESIG_BEAT = 18
DISPLAY_GROUP_NAME = 231
CHANNEL_IS_ENABLED = 0
CHANNEL_NEW = 64
CHANNEL_TYPE = 21
CHANNEL_ROUTED_TO = 22
CHANNEL_GROUP_NUM = 145
CHANNEL_NAME = 192
CHANNEL_SAMPLE_PATH = 196
PATTERN_NEW = 65
PATTERN_NAME = 193
PATTERN_NOTES = 224
INSERT_NAME = 204
INSERT_OUTPUT = 147
ARRANGEMENT_NEW = 99
ARRANGEMENT_NAME = 241
ARRANGEMENT_PLAYLIST = 233
ARRANGEMENTS_CURRENT = 100
TRACK_NAME = 239
TRACK_DATA = 238

PATTERN_BASE = 20480
MAX_TRACK_INDEX = 499  # FL >= 12.9.1 stores track index reversed from 499

# Channel type codes.
TYPE_SAMPLER = 0
TYPE_NATIVE = 2


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _event(id_: int, value: int | None = None, *, text: str | None = None,
           data: bytes | None = None) -> bytes:
    if id_ < 64:
        return bytes([id_]) + struct.pack("<B", value)
    if id_ < 128:
        return bytes([id_]) + struct.pack("<H", value)
    if id_ < 192:
        return bytes([id_]) + struct.pack("<I", value)
    payload = data if data is not None else (text or "").encode("utf-16-le") + b"\x00\x00"
    return bytes([id_]) + _varint(len(payload)) + payload


@dataclass(frozen=True)
class NoteSpec:
    position: int
    length: int
    key: int = 60
    velocity: int = 100
    channel: int = 0


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    mixer_track: int = 1
    sample_path: str | None = None
    kind: int = TYPE_SAMPLER


@dataclass(frozen=True)
class PatternSpec:
    iid: int
    name: str
    notes: tuple[NoteSpec, ...] = ()


@dataclass(frozen=True)
class ClipSpec:
    pattern_iid: int
    track: int
    start_ticks: int
    length_ticks: int


@dataclass
class FlpSpec:
    """Everything the builder needs to emit one project."""

    title: str = "Fixture"
    fl_version: str = "21.2.3.4004"
    fl_build: int = 3914
    tempo: float = 140.0
    ppq: int = 96
    time_signature: tuple[int, int] = (4, 4)
    channels: list[ChannelSpec] = field(default_factory=list)
    patterns: list[PatternSpec] = field(default_factory=list)
    clips: list[ClipSpec] = field(default_factory=list)
    track_names: list[str] = field(default_factory=list)
    mixer_names: list[str] = field(default_factory=list)


def _note_bytes(note: NoteSpec) -> bytes:
    # position, flags, rack_channel, length, key, group, fine_pitch, _u1,
    # release, midi_channel, pan, velocity, mod_x, mod_y
    return struct.pack(
        "<IHHIHHBBBBBBBB",
        note.position, 0, note.channel, note.length, note.key, 0,
        0, 0, 0, 0, 64, note.velocity, 0, 0,
    )


def _clip_bytes(clip: ClipSpec) -> bytes:
    return struct.pack(
        "<IHHIHH2sH4sff",
        clip.start_ticks,
        PATTERN_BASE,
        PATTERN_BASE + clip.pattern_iid,
        clip.length_ticks,
        MAX_TRACK_INDEX - clip.track,
        0,
        b"\x78\x00",
        64,
        bytes([64, 100, 128, 128]),
        0.0,
        0.0,
    )


def build_flp(spec: FlpSpec) -> bytes:
    """Serialise ``spec`` into .flp bytes that PyFLP parses."""
    body = bytearray()

    # FLVersion is always ASCII: the parser reads it to decide whether the
    # remaining text events are ASCII (< FL 11.5) or UTF-16.
    body += _event(FL_VERSION, data=spec.fl_version.encode("ascii") + b"\x00")
    body += _event(FL_BUILD, spec.fl_build)
    body += _event(TEMPO, round(spec.tempo * 1000))
    body += _event(TITLE, text=spec.title)
    body += _event(TIMESIG_NUM, spec.time_signature[0])
    body += _event(TIMESIG_BEAT, spec.time_signature[1])

    # PyFLP indexes DisplayGroup by channel group number, so at least one must
    # exist or channel iteration raises IndexError.
    body += _event(DISPLAY_GROUP_NAME, text="Unsorted")

    # PyFLP divides the mixer into inserts on InsertID.Output, so a name alone
    # yields nothing; each insert needs its terminating Output event.
    for name in spec.mixer_names:
        body += _event(INSERT_NAME, text=name)
        body += _event(INSERT_OUTPUT, 0)

    for index, channel in enumerate(spec.channels):
        body += _event(CHANNEL_NEW, index)
        body += _event(CHANNEL_TYPE, channel.kind)
        body += _event(CHANNEL_IS_ENABLED, 1)
        body += _event(CHANNEL_NAME, text=channel.name)
        body += _event(CHANNEL_ROUTED_TO, channel.mixer_track)
        body += _event(CHANNEL_GROUP_NUM, 0)
        if channel.sample_path is not None:
            body += _event(CHANNEL_SAMPLE_PATH, text=channel.sample_path)

    for pattern in spec.patterns:
        body += _event(PATTERN_NEW, pattern.iid)
        body += _event(PATTERN_NAME, text=pattern.name)
        if pattern.notes:
            body += _event(
                PATTERN_NOTES, data=b"".join(_note_bytes(n) for n in pattern.notes)
            )

    body += _event(ARRANGEMENT_NEW, 0)
    body += _event(ARRANGEMENT_NAME, text="Arrangement")
    if spec.clips:
        body += _event(
            ARRANGEMENT_PLAYLIST, data=b"".join(_clip_bytes(c) for c in spec.clips)
        )
    for name in spec.track_names:
        body += _event(TRACK_NAME, text=name)
        body += _event(TRACK_DATA, data=struct.pack("<IIIB", 1, 0, 0, 1))
    # Terminates the last arrangement's event subtree.
    body += _event(ARRANGEMENTS_CURRENT, 0)

    header = struct.pack("4sIh2H", b"FLhd", 6, 0, len(spec.channels), spec.ppq)
    return header + b"FLdt" + struct.pack("<I", len(body)) + bytes(body)


def write_flp(spec: FlpSpec, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_flp(spec))
    return path


# --------------------------------------------------------------------------- #
# Named fixtures, mirroring the corpus slices in SPEC.md section 8
# --------------------------------------------------------------------------- #

def _four_on_the_floor(bars: int = 4, ppq: int = 96) -> tuple[NoteSpec, ...]:
    step = ppq  # one beat
    return tuple(
        NoteSpec(position=i * step, length=step // 2, key=60, velocity=100)
        for i in range(bars * 4)
    )


def empty_project() -> FlpSpec:
    """No channels, no patterns, no playlist."""
    return FlpSpec(title="Empty")


def one_pattern_loop() -> FlpSpec:
    """A single 4-bar drum pattern placed once on the playlist."""
    ppq = 96
    return FlpSpec(
        title="One Pattern",
        tempo=140.0,
        ppq=ppq,
        channels=[ChannelSpec(name="Kick", mixer_track=1)],
        patterns=[PatternSpec(iid=1, name="Drums", notes=_four_on_the_floor(4, ppq))],
        clips=[ClipSpec(pattern_iid=1, track=0, start_ticks=0, length_ticks=ppq * 16)],
        track_names=["Drums"],
        mixer_names=["Master", "Kick"],
    )


def multi_pattern_loop() -> FlpSpec:
    """Drums plus a chord pattern - the shape a role classifier must handle."""
    ppq = 96
    chords = tuple(
        NoteSpec(position=bar * ppq * 4, length=ppq * 4, key=key, velocity=90, channel=1)
        for bar in range(4)
        for key in (60, 63, 67)
    )
    return FlpSpec(
        title="Multi Pattern",
        tempo=92.0,
        ppq=ppq,
        channels=[
            ChannelSpec(name="Kick", mixer_track=1, sample_path="D:\\Drums\\Kick.wav"),
            ChannelSpec(name="Rhodes Chords", mixer_track=2, kind=TYPE_NATIVE),
        ],
        patterns=[
            PatternSpec(iid=1, name="Drums", notes=_four_on_the_floor(4, ppq)),
            PatternSpec(iid=2, name="Chords", notes=chords),
        ],
        clips=[
            ClipSpec(pattern_iid=1, track=0, start_ticks=0, length_ticks=ppq * 16),
            ClipSpec(pattern_iid=2, track=1, start_ticks=0, length_ticks=ppq * 16),
        ],
        track_names=["Drums", "Chords"],
        mixer_names=["Master", "Drums", "Keys"],
    )


def missing_sample_project() -> FlpSpec:
    """References a sample path that cannot exist on any test machine."""
    spec = one_pattern_loop()
    spec.title = "Missing Sample"
    spec.channels = [
        ChannelSpec(
            name="Snare",
            mixer_track=2,
            sample_path="Z:\\definitely\\not\\here\\Snare21.wav",
        )
    ]
    return spec


def odd_time_signature() -> FlpSpec:
    spec = one_pattern_loop()
    spec.title = "Seven Four"
    spec.time_signature = (7, 4)
    return spec


def arranged_project() -> FlpSpec:
    """Same pattern tiled across 16 bars - reads as 'arranged', not 'loop'."""
    ppq = 96
    spec = one_pattern_loop()
    spec.title = "Arranged"
    spec.clips = [
        ClipSpec(pattern_iid=1, track=0, start_ticks=ppq * 16 * i,
                 length_ticks=ppq * 16)
        for i in range(4)
    ]
    return spec


#: Every named fixture, for corpus-style sweeps.
FIXTURES: dict[str, callable[[], FlpSpec]] = {
    "empty": empty_project,
    "one_pattern": one_pattern_loop,
    "multi_pattern": multi_pattern_loop,
    "missing_sample": missing_sample_project,
    "odd_time_signature": odd_time_signature,
    "arranged": arranged_project,
}

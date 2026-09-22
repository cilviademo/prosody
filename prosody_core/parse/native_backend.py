"""A second parser that owes PyFLP nothing.

Built on ``write/eventstream.read_flp``, which splits the event stream by the
format's own rule (id < 64 → 1 byte, < 128 → 2, < 192 → 4, otherwise a varint
length) and never re-slices bytes afterwards. That is the whole point: on the
studio PC, PyFLP 2.2.1 failed on a project saved by FL Studio 2026 with a
UTF-16 decode error whose payload contained *several whole events joined
together* — a fault above the splitter, in PyFLP's string layer. A reader that
only splits cannot reproduce it.

This backend is deliberately narrower than PyFLP. It reads what the product
needs — version, tempo, time signature, channels, patterns with notes, the
playlist, markers, mixer insert names — and records everything it skipped in
``unknown_event_ids`` so nothing is silently lost. It decodes text with
``errors="replace"`` and says so, rather than raising on a single odd byte.

Where PyFLP succeeds it remains the primary backend; this one runs when PyFLP
raises, and can be asked for directly (``flpf inspect --backend native``) to
compare the two on the same file.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prosody_core.fs.safety import sha256_file
from prosody_core.model.schemas import (
    Arrangement,
    BeatProject,
    Channel,
    ChannelKind,
    Marker,
    MixerInsert,
    Note,
    ParseWarning,
    Pattern,
    PlaylistClip,
    PlaylistTrack,
    Severity,
)
from prosody_core.write.eventstream import FLP_HEADER, HEADER_SIZE, Event, read_flp

# --- event ids, numerically, so this file has no import-time PyFLP dependency ---
# Values match PyFLP 2.2.1's enums (ProjectID, ChannelID, PatternID,
# ArrangementID, TrackID, TimeMarkerID, InsertID, PluginID, DisplayGroupID).
CHANNEL_IS_ENABLED = 0
TIMESIG_NUM, TIMESIG_BEAT = 17, 18
CHANNEL_TYPE, CHANNEL_ROUTED_TO = 21, 22
CHANNEL_NEW, PATTERN_NEW = 64, 65
TEMPO_COARSE = 66
ARRANGEMENT_NEW, ARRANGEMENTS_CURRENT = 99, 100
CHANNEL_GROUP_NUM = 145
INSERT_OUTPUT = 147
MARKER_POSITION = 148
TEMPO = 156
FL_BUILD = 159
PATTERN_LENGTH = 164
CHANNEL_NAME = 192
PATTERN_NAME = 193
TITLE = 194
CHANNEL_SAMPLE_PATH = 196
FL_VERSION = 199
PLUGIN_INTERNAL_NAME = 201
PLUGIN_NAME = 203
INSERT_NAME = 204
MARKER_NAME = 205
PATTERN_NOTES = 224
DISPLAY_GROUP_NAME = 231
ARRANGEMENT_PLAYLIST = 233
TRACK_DATA = 238
TRACK_NAME = 239
ARRANGEMENT_NAME = 241

#: Every id this backend gives meaning to. Anything else is reported.
KNOWN_IDS = frozenset({
    33, 34,  # TimeMarkerID.Numerator / Denominator
    CHANNEL_IS_ENABLED, TIMESIG_NUM, TIMESIG_BEAT, CHANNEL_TYPE, CHANNEL_ROUTED_TO,
    CHANNEL_NEW, PATTERN_NEW, TEMPO_COARSE, ARRANGEMENT_NEW, ARRANGEMENTS_CURRENT,
    CHANNEL_GROUP_NUM, INSERT_OUTPUT, MARKER_POSITION, TEMPO, FL_BUILD, PATTERN_LENGTH,
    CHANNEL_NAME, PATTERN_NAME, TITLE, CHANNEL_SAMPLE_PATH, FL_VERSION,
    PLUGIN_INTERNAL_NAME, PLUGIN_NAME, INSERT_NAME, MARKER_NAME, PATTERN_NOTES,
    DISPLAY_GROUP_NAME, ARRANGEMENT_PLAYLIST, TRACK_DATA, TRACK_NAME, ARRANGEMENT_NAME,
})

#: ``ChannelID.Type`` codes, per PyFLP's ``ChannelType``.
_KIND_BY_TYPE = {
    0: ChannelKind.SAMPLER,
    2: ChannelKind.PLUGIN,      # native FL instrument
    3: ChannelKind.LAYER,
    4: ChannelKind.PLUGIN,      # third-party (VST) instrument
    5: ChannelKind.AUTOMATION,
}

NOTE_RECORD = struct.Struct("<IHHIHHBBBBBBBB")      # 24 bytes, FL >= 12
CLIP_RECORD = struct.Struct("<IHHIHH2sH4sff")        # 32 bytes, FL >= 12.9.1
PATTERN_BASE = 20480
MAX_TRACK_INDEX = 499

#: Text is UTF-16 from FL 11.5; older projects are ASCII. FLVersion is always ASCII.
UNICODE_FROM = (11, 5)
#: The newest FL Studio line PyFLP 2.2.1 was written against.
PYFLP_SUPPORTS_UP_TO = "20.9"


def _version_tuple(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    parts: list[int] = []
    for piece in version.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def fl_version_of(path: Path) -> str | None:
    """The saving FL Studio's version, read before any full parse.

    ``FLVersion`` (199) is ASCII in every project ever written, so this works
    on files the rest of the parser cannot read — which is when it matters.
    """
    try:
        flp = read_flp(Path(path), strict=False)
    except Exception:  # noqa: BLE001 - a header we cannot read has no version
        return None
    for event in flp.events:
        if event.id == FL_VERSION:
            return event.payload.decode("ascii", "replace").rstrip("\0") or None
    return None


#: The first year-numbered edition. FL 2024 introduced channel-rack display
#: groups and the studio PC's FL 2026 project is the one PyFLP could not read;
#: 21.x-23.x are simply unverified, which is a different claim.
FIRST_YEAR_EDITION = 2024


def newer_than_pyflp_supports(version: str | None) -> bool:
    """True for projects saved by an FL Studio newer than has been verified.

    Compared on the verified version's own precision: ``20.9.2.2963`` is a
    20.9 build, not something newer than it.
    """
    supported = _version_tuple(PYFLP_SUPPORTS_UP_TO)
    return _version_tuple(version)[: len(supported)] > supported


def version_notice(version: str) -> tuple[str, Severity]:
    """The warning for a newer project, and how loudly to say it.

    Below the year-numbered editions nothing is known to break, so it is an
    INFO note; from FL 2024 on a real failure has been seen, so it warns.
    """
    major = (_version_tuple(version) or (0,))[0]
    severity = Severity.WARNING if major >= FIRST_YEAR_EDITION else Severity.INFO
    return (
        f"Saved with FL Studio {version}. Prosody has been verified on projects up to "
        f"FL {PYFLP_SUPPORTS_UP_TO}; if anything looks missing, Copy event inventory on the "
        "project screen gives a report to send.",
        severity,
    )


@dataclass
class _Sink:
    items: list[ParseWarning] = field(default_factory=list)
    _seen: set[tuple[str, str]] = field(default_factory=set)

    def add(self, code: str, message: str, severity: Severity = Severity.WARNING) -> None:
        if (code, message) in self._seen:
            return
        self._seen.add((code, message))
        self.items.append(ParseWarning(code=code, message=message, severity=severity))


@dataclass
class _ChannelDraft:
    index: int
    name: str | None = None
    kind: ChannelKind = ChannelKind.UNKNOWN
    plugin: str | None = None
    sample_path: str | None = None
    mixer_track: int | None = None
    enabled: bool = True


@dataclass
class _PatternDraft:
    index: int
    name: str | None = None
    length: int = 0
    notes: list[Note] = field(default_factory=list)


MARKER_IDS = frozenset({33, 34, MARKER_POSITION, MARKER_NAME})   # TimeMarkerID.*
TRACK_IDS = frozenset({TRACK_DATA, TRACK_NAME})                   # TrackID.*


@dataclass
class _ArrangementDraft:
    index: int
    name: str | None = None
    clips: list[PlaylistClip] = field(default_factory=list)
    #: One entry per TrackID.Data event, in file order — the track index.
    track_names: list[str | None] = field(default_factory=list)
    #: One entry per contiguous run of TimeMarkerID events: [position, name].
    markers: list[list[Any]] = field(default_factory=list)


@dataclass
class _InsertDraft:
    index: int
    name: str | None = None
    effects: list[str] = field(default_factory=list)


class NativeBackend:
    """Implements :class:`~prosody_core.parse.adapter.ParserBackend`."""

    @property
    def name(self) -> str:
        return "native"

    def parse(self, path: Path) -> BeatProject:
        path = Path(path)
        digest = sha256_file(path)
        size = path.stat().st_size
        sink = _Sink()

        flp = read_flp(path, strict=False)
        if flp.truncated_by:
            sink.add(
                "file_truncated",
                f"the data chunk declares {flp.truncated_by} more bytes than the "
                "file holds; the tail was not read",
            )
        _, _, fmt, _header_channels, ppq = FLP_HEADER.unpack(flp.header[:HEADER_SIZE])

        version = next(
            (e.payload.decode("ascii", "replace").rstrip("\0") for e in flp.events if e.id == FL_VERSION),
            None,
        )
        unicode = _version_tuple(version) >= UNICODE_FROM if version else True
        replaced = False

        def text(event: Event) -> str:
            nonlocal replaced
            raw = event.payload
            if unicode and len(raw) % 2:
                # An odd byte count can only be a trailing NUL or a stray byte;
                # dropping it is what "replace" would render as U+FFFD anyway.
                raw = raw[:-1]
            decoded = raw.decode("utf-16-le" if unicode else "latin-1", "replace")
            if "�" in decoded:
                replaced = True
            return decoded.rstrip("\0")

        tempo: float | None = None
        build: int | None = None
        title: str | None = None
        timesig = [4, 4]
        channels: list[_ChannelDraft] = []
        patterns: dict[int, _PatternDraft] = {}
        arrangements: list[_ArrangementDraft] = []
        inserts: list[_InsertDraft] = []
        current: str | None = None      # "channel" | "pattern" | "arrangement" | "insert"
        unknown: set[int] = set()
        previous_id: int | None = None  # for grouping contiguous marker events

        def insert_open() -> _InsertDraft:
            if not inserts or (inserts[-1].name is not None and current != "insert"):
                inserts.append(_InsertDraft(index=len(inserts)))
            return inserts[-1]

        for event in flp.events:
            eid, payload = event.id, event.payload
            if eid == FL_VERSION:
                continue
            if eid == FL_BUILD:
                build = int.from_bytes(payload, "little")
            elif eid == TEMPO:
                tempo = int.from_bytes(payload, "little") / 1000.0
            elif eid == TEMPO_COARSE and tempo is None:
                tempo = float(int.from_bytes(payload, "little"))
            elif eid == TITLE:
                title = text(event) or None
            elif eid == TIMESIG_NUM:
                timesig[0] = payload[0] or 4
            elif eid == TIMESIG_BEAT:
                timesig[1] = payload[0] or 4
            elif eid == DISPLAY_GROUP_NAME:
                text(event)  # decoded for the replace-check; groups are not modelled
            # -- channels ---------------------------------------------------- #
            elif eid == CHANNEL_NEW:
                channels.append(_ChannelDraft(index=int.from_bytes(payload, "little")))
                current = "channel"
            elif eid == CHANNEL_TYPE and channels:
                channels[-1].kind = _KIND_BY_TYPE.get(payload[0], ChannelKind.UNKNOWN)
            elif eid == CHANNEL_IS_ENABLED and current == "channel" and channels:
                channels[-1].enabled = bool(payload[0])
            elif eid == CHANNEL_NAME and channels:
                channels[-1].name = text(event) or None
            elif eid == CHANNEL_SAMPLE_PATH and channels:
                channels[-1].sample_path = text(event) or None
            elif eid == CHANNEL_ROUTED_TO and channels:
                channels[-1].mixer_track = int.from_bytes(payload, "little")
            elif eid == PLUGIN_INTERNAL_NAME:
                name = text(event) or None
                if current == "channel" and channels:
                    channels[-1].plugin = name
                elif name:
                    insert_open().effects.append(name)
            elif eid == PLUGIN_NAME:
                text(event)  # display name; internal name is the identity
            elif eid == CHANNEL_GROUP_NUM:
                pass
            # -- patterns ---------------------------------------------------- #
            elif eid == PATTERN_NEW:
                iid = int.from_bytes(payload, "little")
                patterns.setdefault(iid, _PatternDraft(index=iid))
                current = ("pattern", iid)  # type: ignore[assignment]
            elif eid == PATTERN_NAME and isinstance(current, tuple):
                patterns[current[1]].name = text(event) or None
            elif eid == PATTERN_LENGTH and isinstance(current, tuple):
                patterns[current[1]].length = int.from_bytes(payload, "little")
            elif eid == PATTERN_NOTES and isinstance(current, tuple):
                draft = patterns[current[1]]
                whole = len(payload) - len(payload) % NOTE_RECORD.size
                if whole != len(payload):
                    sink.add("pattern_notes_partial_record",
                             f"pattern {draft.index} note data is not a whole number of 24-byte records")
                for off in range(0, whole, NOTE_RECORD.size):
                    (pos, _flags, rack, length, key, _group, _fine, _u1, _rel, _midi,
                     pan, vel, _mx, _my) = NOTE_RECORD.unpack_from(payload, off)
                    draft.notes.append(Note(
                        channel=rack, position=max(pos, 0), length=max(length, 0),
                        key=max(0, min(131, key)), velocity=max(0, min(127, vel)),
                        pan=max(0, min(127, pan)),
                    ))
            # -- arrangements ------------------------------------------------ #
            elif eid == ARRANGEMENT_NEW:
                arrangements.append(_ArrangementDraft(index=int.from_bytes(payload, "little")))
                current = "arrangement"
            elif eid == ARRANGEMENT_NAME and arrangements:
                arrangements[-1].name = text(event) or None
            elif eid == ARRANGEMENT_PLAYLIST and arrangements:
                arr = arrangements[-1]
                whole = len(payload) - len(payload) % CLIP_RECORD.size
                if whole != len(payload):
                    sink.add("playlist_partial_record",
                             "playlist data is not a whole number of 32-byte records")
                for off in range(0, whole, CLIP_RECORD.size):
                    (pos, base, item, length, rvidx, _grp, _u, _flags, _u2,
                     _so, _eo) = CLIP_RECORD.unpack_from(payload, off)
                    track = max(MAX_TRACK_INDEX - rvidx, 0)
                    if item > base:
                        arr.clips.append(PlaylistClip(
                            track=track, kind="pattern", pattern=item - base,
                            start_ticks=max(pos, 0), length_ticks=max(length, 0)))
                    else:
                        arr.clips.append(PlaylistClip(
                            track=track, kind="channel", channel=item,
                            start_ticks=max(pos, 0), length_ticks=max(length, 0)))
            # Tracks: a Data event opens one; the Name after it belongs to it.
            # This is PyFLP's divide(TrackID.Data, *TrackID), and it is what
            # keeps names on the right rows of a real 500-track playlist.
            elif eid == TRACK_DATA and arrangements:
                arrangements[-1].track_names.append(None)
            elif eid == TRACK_NAME and arrangements:
                names = arrangements[-1].track_names
                if not names:
                    names.append(None)
                names[-1] = text(event) or None
            # Markers: one per contiguous run of TimeMarkerID events, which is
            # PyFLP's group(*TimeMarkerID); order inside the run does not matter.
            elif eid in MARKER_IDS and arrangements:
                marks = arrangements[-1].markers
                if previous_id not in MARKER_IDS or not marks:
                    marks.append([0, None])
                if eid == MARKER_POSITION:
                    marks[-1][0] = int.from_bytes(payload, "little")
                elif eid == MARKER_NAME:
                    marks[-1][1] = text(event) or None
            elif eid == ARRANGEMENTS_CURRENT:
                current = None
            # -- mixer ------------------------------------------------------- #
            elif eid == INSERT_NAME:
                current = "insert"
                if not inserts or inserts[-1].name is not None:
                    inserts.append(_InsertDraft(index=len(inserts)))
                inserts[-1].name = text(event) or None
            elif eid == INSERT_OUTPUT:
                if inserts and inserts[-1].name is None and not inserts[-1].effects:
                    pass
                current = "insert"
                inserts.append(_InsertDraft(index=len(inserts)))
            elif eid not in KNOWN_IDS:
                unknown.add(eid)
            previous_id = eid

        # A trailing empty insert opened by the last Output event is not real.
        while inserts and inserts[-1].name is None and not inserts[-1].effects:
            inserts.pop()

        if replaced:
            sink.add("text_decode_replaced",
                     "some text could not be decoded cleanly and was read with "
                     "replacement characters", Severity.INFO)
        if version and newer_than_pyflp_supports(version):
            message, severity = version_notice(version)
            sink.add("fl_version_newer", message, severity)
        sink.add("native_backend",
                 "read by Prosody's own event reader rather than PyFLP", Severity.INFO)

        out_patterns = tuple(
            Pattern(
                index=d.index, name=d.name,
                length_ticks=max(d.length or (max((n.position + n.length for n in d.notes), default=0)), 0),
                notes=tuple(d.notes),
            )
            for _, d in sorted(patterns.items())
        )
        out_arrangements = []
        for d in arrangements:
            n_tracks = max(len(d.track_names), max((c.track + 1 for c in d.clips), default=0))
            counts: dict[int, int] = {}
            for c in d.clips:
                counts[c.track] = counts.get(c.track, 0) + 1
            tracks = tuple(
                PlaylistTrack(index=i,
                              name=d.track_names[i] if i < len(d.track_names) else None,
                              clip_count=counts.get(i, 0))
                for i in range(n_tracks)
            )
            markers = tuple(
                Marker(position_ticks=max(int(pos), 0), name=name) for pos, name in d.markers
            )
            out_arrangements.append(Arrangement(
                index=d.index, name=d.name, tracks=tracks, clips=tuple(d.clips), markers=markers))

        out_channels = tuple(
            Channel(index=c.index, name=c.name, kind=c.kind, plugin=c.plugin,
                    sample_path=c.sample_path, mixer_track=c.mixer_track, enabled=c.enabled)
            for c in channels
        )
        length_ticks = max(
            (c.start_ticks + c.length_ticks for a in out_arrangements for c in a.clips),
            default=max((p.length_ticks for p in out_patterns), default=0),
        )

        return BeatProject(
            id=digest, source_path=str(path), source_bytes=size, backend=self.name,
            fl_version=version, fl_build=build, format=int(fmt),
            tempo=tempo, ppq=int(ppq) or 96,
            time_signature=(timesig[0], timesig[1]),
            length_ticks=length_ticks, title=title,
            channels=out_channels, patterns=out_patterns,
            mixer=tuple(MixerInsert(index=i.index, name=i.name, effects=tuple(i.effects)) for i in inserts),
            arrangements=tuple(out_arrangements),
            samples=_samples(out_channels), plugins=_plugins(out_channels),
            unknown_event_ids=tuple(sorted(unknown)),
            parse_warnings=tuple(sink.items),
        )


def _samples(channels: tuple[Channel, ...]) -> tuple[Any, ...]:
    from prosody_core.model.schemas import SampleRef

    grouped: dict[str, list[int]] = {}
    for ch in channels:
        if ch.sample_path:
            grouped.setdefault(ch.sample_path, []).append(ch.index)
    return tuple(
        SampleRef(path=p, found=Path(p).is_file(), used_by_channels=tuple(u))
        for p, u in sorted(grouped.items())
    )


def _plugins(channels: tuple[Channel, ...]) -> tuple[Any, ...]:
    from prosody_core.model.schemas import PluginRef

    grouped: dict[str, list[int]] = {}
    for ch in channels:
        if ch.plugin:
            grouped.setdefault(ch.plugin, []).append(ch.index)
    return tuple(PluginRef(name=n, used_by_channels=tuple(u)) for n, u in sorted(grouped.items()))

"""PyFLP implementation of :class:`ParserBackend`.

Design rule for this module: *one broken section must not lose the whole
project*. Every extraction step is wrapped; a failure becomes a
:class:`ParseWarning` on the resulting :class:`BeatProject` instead of an
exception. Only a failure to read the file header at all is fatal.

The source file is opened read-only and never written, moved or renamed.
"""

from __future__ import annotations

import importlib.metadata as _md
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from typing import Any, TypeVar

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
    PluginRef,
    SampleRef,
    Severity,
)
from prosody_core.parse import _pyflp_compat
from prosody_core.parse.adapter import ParseError
from prosody_core.parse.native_backend import (
    NativeBackend,
    newer_than_pyflp_supports,
    version_notice,
)

T = TypeVar("T")

_COMPAT_APPLIED = _pyflp_compat.apply()


def pyflp_version() -> str:
    try:
        return _md.version("pyflp")
    except _md.PackageNotFoundError:  # pragma: no cover
        return "unknown"


class _WarningSink:
    """Collects degradation notices while parsing."""

    def __init__(self) -> None:
        self._items: list[ParseWarning] = []
        self._seen: set[tuple[str, str]] = set()

    def add(self, code: str, message: str, severity: Severity = Severity.WARNING) -> None:
        """Record a notice once. A 100-channel project must not emit 100 copies
        of the same message."""
        if (code, message) in self._seen:
            return
        self._seen.add((code, message))
        self._items.append(ParseWarning(code=code, message=message, severity=severity))

    def guard(self, code: str, default: T, fn: Callable[[], T]) -> T:
        """Run ``fn``; on any failure record a warning and return ``default``."""
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - deliberate: degrade, don't crash
            self.add(code, f"{type(exc).__name__}: {exc}")
            return default

    @property
    def items(self) -> tuple[ParseWarning, ...]:
        return tuple(self._items)


def _channel_kind(raw: Any) -> ChannelKind:
    name = type(raw).__name__.lower()
    if name == "automation":
        return ChannelKind.AUTOMATION
    if name == "layer":
        return ChannelKind.LAYER
    if name == "sampler":
        return ChannelKind.SAMPLER
    if name == "instrument":
        return ChannelKind.PLUGIN
    return ChannelKind.UNKNOWN


class PyFLPBackend:
    """Implements :class:`~prosody_core.parse.adapter.ParserBackend`."""

    @property
    def name(self) -> str:
        suffix = "+compat" if _COMPAT_APPLIED else ""
        return f"pyflp-{pyflp_version()}{suffix}"

    def parse(self, path: Path) -> BeatProject:
        import pyflp  # imported here so the shim is applied first

        path = Path(path)
        digest = sha256_file(path)
        size = path.stat().st_size

        try:
            project = pyflp.parse(path)
        except Exception as exc:  # noqa: BLE001 - deliberate: any PyFLP failure falls back
            # PyFLP's string layer, not the file, is the usual reason a project
            # FL Studio opens fine cannot be read here (seen on FL 2026). The
            # native reader splits by the format's own rule and re-slices
            # nothing, so it is tried before giving up. The original exception
            # is kept as an INFO warning for Diagnostics, never as the headline.
            fallback = NativeBackend()
            try:
                result = fallback.parse(path)
            except Exception as native_exc:
                raise ParseError(path, exc) from native_exc
            if any(w.code == "file_truncated" for w in result.parse_warnings):
                # A byte count that contradicts the header is damage, not a
                # parser gap. The automatic fallback must not make a broken
                # file look readable; `--backend native` remains available for
                # looking inside one on purpose.
                raise ParseError(path, exc) from None
            return result.model_copy(update={
                "backend": "native (pyflp failed)",
                "parse_warnings": (
                    *result.parse_warnings,
                    ParseWarning(
                        code="pyflp_failed",
                        message=f"PyFLP could not read this project: {type(exc).__name__}: {exc}",
                        severity=Severity.INFO,
                    ),
                ),
            })

        w = _WarningSink()
        version_text = w.guard("fl_version", None, lambda: str(project.version))
        if version_text and newer_than_pyflp_supports(version_text):
            message, severity = version_notice(version_text)
            w.add("fl_version_newer", message, severity)
        channels = self._channels(project, w)
        patterns = self._patterns(project, w)
        mixer = self._mixer(project, w)
        arrangements = self._arrangements(project, w)

        length_ticks = self._length_ticks(patterns, arrangements)
        ppq = w.guard("ppq", 96, lambda: int(project.ppq) or 96)

        return BeatProject(
            id=digest,
            source_path=str(path),
            source_bytes=size,
            backend=self.name,
            fl_version=version_text,
            format=w.guard("format", None, lambda: int(project.format)),
            tempo=w.guard("tempo", None, lambda: float(project.tempo)),
            ppq=ppq,
            time_signature=self._time_signature(project, w),
            length_ticks=length_ticks,
            title=w.guard("title", None, lambda: project.title or None),
            channels=channels,
            patterns=patterns,
            mixer=mixer,
            arrangements=arrangements,
            samples=self._samples(channels),
            plugins=self._plugins(channels),
            unknown_event_ids=self._unknown_event_ids(project, w),
            parse_warnings=w.items,
        )

    # -- sections ---------------------------------------------------------- #

    def _time_signature(self, project: Any, w: _WarningSink) -> tuple[int, int]:
        def read() -> tuple[int, int]:
            ts = project.arrangements.time_signature
            return (int(ts.num or 4), int(ts.beat or 4))

        return w.guard("time_signature", (4, 4), read)

    def _channels(self, project: Any, w: _WarningSink) -> tuple[Channel, ...]:
        def read() -> tuple[Channel, ...]:
            out: list[Channel] = []
            for raw in project.channels:
                sub = _WarningSink()
                out.append(
                    Channel(
                        index=int(raw.iid),
                        name=sub.guard("channel_name", None, lambda r=raw: r.name or None),
                        kind=_channel_kind(raw),
                        plugin=sub.guard(
                            "channel_plugin", None,
                            lambda r=raw: getattr(r, "internal_name", None) or None,
                        ),
                        sample_path=sub.guard(
                            "channel_sample", None,
                            lambda r=raw: str(r.sample_path) if getattr(r, "sample_path", None) else None,
                        ),
                        mixer_track=sub.guard(
                            "channel_insert", None,
                            lambda r=raw: int(r.insert) if getattr(r, "insert", None) is not None else None,
                        ),
                        enabled=bool(sub.guard("channel_enabled", True, lambda r=raw: r.enabled)),
                    )
                )
                for item in sub.items:
                    w.add(item.code, item.message, item.severity)
            return tuple(out)

        return w.guard("channels", (), read)

    def _patterns(self, project: Any, w: _WarningSink) -> tuple[Pattern, ...]:
        def read() -> tuple[Pattern, ...]:
            out: list[Pattern] = []
            for raw in project.patterns:
                sub = _WarningSink()
                notes = sub.guard("pattern_notes", (), lambda r=raw: tuple(_notes(r)))
                length = sub.guard(
                    "pattern_length", 0, lambda r=raw: int(r.length or 0)
                )
                if not length and notes:
                    length = max(n.position + n.length for n in notes)
                out.append(
                    Pattern(
                        index=int(raw.iid),
                        name=sub.guard("pattern_name", None, lambda r=raw: r.name or None),
                        length_ticks=max(length, 0),
                        notes=notes,
                    )
                )
                for item in sub.items:
                    w.add(item.code, item.message, item.severity)
            return tuple(out)

        return w.guard("patterns", (), read)

    def _mixer(self, project: Any, w: _WarningSink) -> tuple[MixerInsert, ...]:
        def read() -> tuple[MixerInsert, ...]:
            out: list[MixerInsert] = []
            for idx, insert in enumerate(project.mixer):
                sub = _WarningSink()
                effects = _insert_effects(insert, sub)
                out.append(
                    MixerInsert(
                        index=idx,
                        name=sub.guard("mixer_name", None, lambda i=insert: i.name or None),
                        effects=effects,
                    )
                )
                for item in sub.items:
                    w.add(item.code, item.message, item.severity)
            return tuple(out)

        return w.guard("mixer", (), read)

    def _arrangements(self, project: Any, w: _WarningSink) -> tuple[Arrangement, ...]:
        def read() -> tuple[Arrangement, ...]:
            out: list[Arrangement] = []
            for raw in project.arrangements:
                sub = _WarningSink()
                tracks, clips = sub.guard(
                    "arrangement_tracks", ((), ()), partial(_tracks_and_clips, raw)
                )
                markers = sub.guard(
                    "arrangement_markers", (), partial(_markers, raw)
                )
                out.append(
                    Arrangement(
                        index=int(getattr(raw, "iid", 0) or 0),
                        name=getattr(raw, "name", None) or None,
                        tracks=tracks,
                        clips=clips,
                        markers=markers,
                    )
                )
                for item in sub.items:
                    w.add(item.code, item.message, item.severity)
            return tuple(out)

        return w.guard("arrangements", (), read)

    # -- derived ----------------------------------------------------------- #

    @staticmethod
    def _length_ticks(
        patterns: tuple[Pattern, ...], arrangements: tuple[Arrangement, ...]
    ) -> int:
        """Longest playlist extent; falls back to the longest pattern."""
        end = 0
        for arrangement in arrangements:
            for clip in arrangement.clips:
                end = max(end, clip.start_ticks + clip.length_ticks)
        if end:
            return end
        return max((p.length_ticks for p in patterns), default=0)

    @staticmethod
    def _samples(channels: tuple[Channel, ...]) -> tuple[SampleRef, ...]:
        grouped: dict[str, list[int]] = {}
        for channel in channels:
            if channel.sample_path:
                grouped.setdefault(channel.sample_path, []).append(channel.index)
        return tuple(
            SampleRef(path=path, found=Path(path).is_file(), used_by_channels=tuple(users))
            for path, users in sorted(grouped.items())
        )

    @staticmethod
    def _plugins(channels: tuple[Channel, ...]) -> tuple[PluginRef, ...]:
        grouped: dict[str, list[int]] = {}
        for channel in channels:
            if channel.plugin:
                grouped.setdefault(channel.plugin, []).append(channel.index)
        return tuple(
            PluginRef(name=name, used_by_channels=tuple(users))
            for name, users in sorted(grouped.items())
        )

    @staticmethod
    def _unknown_event_ids(project: Any, w: _WarningSink) -> tuple[int, ...]:
        """Event ids PyFLP produced no typed model for.

        Recorded so a later writer can prove it preserved them (EXECUTE T1:
        "keep unknown PyFLP events; never drop them").
        """

        def read() -> tuple[int, ...]:
            from pyflp._events import UnknownDataEvent

            ids = {
                int(event.id)
                for event in project.events
                if isinstance(event, UnknownDataEvent)
            }
            return tuple(sorted(ids))

        return w.guard("unknown_events", (), read)


#: PyFLP renders ``Note.key`` as a name ("C5", "A#3"); sharps only, C5 == 60.
_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_NOTE_NAME_TO_PC = {name: i for i, name in enumerate(_NOTE_NAMES)}


def key_number(raw_note: Any) -> int:
    """FL's 0-131 key number for a PyFLP note.

    The raw struct field is preferred; the displayed name is only parsed as a
    fallback, because PyFLP formats it as ``NAMES[k % 12] + str(k // 12)``.
    """
    try:
        return int(raw_note["key"])
    except Exception:  # noqa: BLE001 - fall through to the name form
        pass

    name = str(raw_note.key)
    pitch = name.rstrip("-0123456789")
    octave = name[len(pitch):]
    if pitch not in _NOTE_NAME_TO_PC or not octave.lstrip("-").isdigit():
        raise ValueError(f"unrecognised note name {name!r}")
    return int(octave) * 12 + _NOTE_NAME_TO_PC[pitch]


def _tracks_and_clips(
    raw_arrangement: Any,
) -> tuple[tuple[PlaylistTrack, ...], tuple[PlaylistClip, ...]]:
    """Playlist tracks and their clips for one arrangement."""
    tracks: list[PlaylistTrack] = []
    clips: list[PlaylistClip] = []
    for track_index, track in enumerate(raw_arrangement.tracks):
        items = list(track)
        tracks.append(
            PlaylistTrack(
                index=track_index,
                name=getattr(track, "name", None) or None,
                clip_count=len(items),
            )
        )
        for item in items:
            clip = _playlist_clip(track_index, item)
            if clip is not None:
                clips.append(clip)
    return tuple(tracks), tuple(clips)


def _markers(raw_arrangement: Any) -> tuple[Marker, ...]:
    return tuple(
        Marker(
            position_ticks=max(int(marker.position or 0), 0),
            name=getattr(marker, "name", None) or None,
        )
        for marker in raw_arrangement.timemarkers
    )


def _insert_effects(insert: Any, w: _WarningSink) -> tuple[str, ...]:
    """Effect plugin names on one mixer insert.

    PyFLP can only enumerate slots when the project carries a ``MixerID.Params``
    event. Minimal and older projects do not, and PyFLP raises ``KeyError`` for
    them. That is not damage - it means the effect chain is simply not
    describable from this file - so it is recorded as INFO, not a warning.
    """
    try:
        return tuple(
            slot.internal_name for slot in insert if getattr(slot, "internal_name", None)
        )
    except KeyError as exc:
        if "params" in str(exc):
            w.add(
                "mixer_slots_undescribable",
                "project has no mixer Params event; insert effect chains cannot "
                "be enumerated by this backend",
                Severity.INFO,
            )
            return ()
        w.add("mixer_slots", f"KeyError: {exc}")
        return ()
    except Exception as exc:  # noqa: BLE001
        w.add("mixer_slots", f"{type(exc).__name__}: {exc}")
        return ()


def _notes(raw_pattern: Any) -> Iterator[Note]:
    for note in raw_pattern.notes:
        yield Note(
            channel=int(note.rack_channel),
            position=max(int(note.position), 0),
            length=max(int(note.length), 0),
            key=max(0, min(131, key_number(note))),
            velocity=max(0, min(127, int(note.velocity))),
            pan=max(0, min(127, int(note.pan))) if note.pan is not None else None,
        )


def _playlist_clip(track_index: int, item: Any) -> PlaylistClip | None:
    """Normalise one playlist item. Returns None for shapes we cannot express."""
    start = max(int(item.position or 0), 0)
    length = max(int(item.length or 0), 0)

    pattern = getattr(item, "pattern", None)
    if pattern is not None:
        return PlaylistClip(
            track=track_index, kind="pattern", pattern=int(pattern.iid),
            start_ticks=start, length_ticks=length,
        )

    channel = getattr(item, "channel", None)
    if channel is not None:
        return PlaylistClip(
            track=track_index, kind="channel", channel=int(channel.iid),
            start_ticks=start, length_ticks=length,
        )
    return None

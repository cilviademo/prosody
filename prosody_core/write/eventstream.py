"""Byte-exact FLP event stream reader and writer.

The safest possible derivative writer: read every event as ``(id, raw_payload)``
and write back exactly those bytes, changing only the events we intend to
change. Nothing is re-encoded through a struct, so plugin state, automation,
mixer routing, sample references and events no parser understands survive
untouched - they are literally the same bytes.

This is deliberately *not* ``pyflp.save()``. That path rebuilds every event from
its parsed value and recomputes the header's channel count, which we have not
verified to be lossless (docs/flp-compatibility.md). Here the header is copied
verbatim and only the payload of a named event is substituted.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from prosody_core.fs.source import atomic_write

FLP_HEADER = struct.Struct("4sIh2H")
HEADER_SIZE = FLP_HEADER.size  # 14
DATA_HEADER_SIZE = 8           # "FLdt" + u32
WORD, DWORD, TEXT = 64, 128, 192


class MalformedFLP(ValueError):
    """The file is not a container we can safely rewrite."""


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Return (value, new_offset)."""
    value = shift = 0
    while True:
        if offset >= len(data):
            raise MalformedFLP("truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7


def write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


@dataclass
class Event:
    """One event, with its payload kept as raw bytes."""

    id: int
    payload: bytes

    def to_bytes(self) -> bytes:
        if self.id < TEXT:
            return bytes([self.id]) + self.payload
        return bytes([self.id]) + write_varint(len(self.payload)) + self.payload


@dataclass
class FLPFile:
    """A parsed container: verbatim header plus an ordered event list."""

    header: bytes
    events: list[Event]

    @property
    def ppq(self) -> int:
        return FLP_HEADER.unpack(self.header)[4]

    @property
    def format(self) -> int:
        return FLP_HEADER.unpack(self.header)[2]

    def index_of(self, event_id: int) -> int | None:
        for i, event in enumerate(self.events):
            if event.id == event_id:
                return i
        return None

    def indexes_of(self, event_id: int) -> list[int]:
        return [i for i, e in enumerate(self.events) if e.id == event_id]

    def count(self, event_id: int) -> int:
        return sum(1 for e in self.events if e.id == event_id)

    def to_bytes(self) -> bytes:
        body = b"".join(event.to_bytes() for event in self.events)
        return self.header + b"FLdt" + struct.pack("<I", len(body)) + body


def payload_size(event_id: int) -> int:
    if event_id < WORD:
        return 1
    if event_id < DWORD:
        return 2
    if event_id < TEXT:
        return 4
    return -1  # variable


def read_flp(path: Path) -> FLPFile:
    """Parse a .flp into a verbatim, rewritable form."""
    raw = Path(path).read_bytes()
    if len(raw) < HEADER_SIZE + DATA_HEADER_SIZE:
        raise MalformedFLP("file is too small to be an FLP")

    header = raw[:HEADER_SIZE]
    magic, size, _fmt, _channels, _ppq = FLP_HEADER.unpack(header)
    if magic != b"FLhd":
        raise MalformedFLP("missing FLhd magic")
    if size != 6:
        raise MalformedFLP(f"unexpected header size {size}")
    if raw[HEADER_SIZE:HEADER_SIZE + 4] != b"FLdt":
        raise MalformedFLP("missing FLdt magic")

    declared = int.from_bytes(raw[HEADER_SIZE + 4:HEADER_SIZE + 8], "little")
    body = raw[HEADER_SIZE + DATA_HEADER_SIZE:]
    if len(body) != declared:
        raise MalformedFLP(
            f"data chunk size mismatch: header says {declared}, file has {len(body)}"
        )

    events: list[Event] = []
    offset = 0
    while offset < len(body):
        event_id = body[offset]
        offset += 1
        fixed = payload_size(event_id)
        if fixed >= 0:
            end = offset + fixed
            if end > len(body):
                raise MalformedFLP(f"truncated payload for event {event_id}")
            events.append(Event(event_id, body[offset:end]))
            offset = end
        else:
            length, offset = read_varint(body, offset)
            end = offset + length
            if end > len(body):
                raise MalformedFLP(f"truncated payload for event {event_id}")
            events.append(Event(event_id, body[offset:end]))
            offset = end

    return FLPFile(header=header, events=events)


def write_flp(flp: FLPFile, path: Path, *, source: Path | None = None) -> Path:
    """Write a project atomically (HARDENING P0.4).

    Passing ``source`` also refuses a destination that resolves to the user's
    original, whatever it is spelled as.
    """
    return atomic_write(Path(path), flp.to_bytes(), source=source)


def diff_events(before: FLPFile, after: FLPFile) -> list[str]:
    """Human-readable list of what changed between two event streams."""
    changes: list[str] = []
    if before.header != after.header:
        changes.append("file header changed")
    if len(before.events) != len(after.events):
        changes.append(
            f"event count {len(before.events)} -> {len(after.events)}"
        )
    for i, (old, new) in enumerate(zip(before.events, after.events, strict=False)):
        if old.id != new.id:
            changes.append(f"event {i}: id {old.id} -> {new.id}")
        elif old.payload != new.payload:
            changes.append(
                f"event {i} (id {old.id}): payload "
                f"{len(old.payload)} -> {len(new.payload)} bytes"
            )
    return changes

"""Does the writer reproduce this file? Asked of every project, answered live.

TESTING_HANDOFF P1.3: the health check said "PyFLP save round-trip unverified
— Phase 0 spike T2 not yet run" on every project, forever. That row can be
answered for the project in hand in a few milliseconds, so it is.

The strongest claim is byte identity: the event reader splits the file and the
writer joins it back, and if the result is the same bytes then nothing the
writer does can lose an event it does not understand. Only when the bytes
differ does the check fall back to comparing structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from prosody_core.write.eventstream import MalformedFLP, read_flp


@dataclass(frozen=True)
class RoundTrip:
    ok: bool | None
    detail: str
    byte_identical: bool = False


def round_trip(path: Path) -> RoundTrip:
    """Read → rewrite → compare, without touching the file."""
    path = Path(path)
    try:
        original = path.read_bytes()
    except OSError as exc:
        return RoundTrip(None, f"could not read the file: {exc}")
    try:
        flp = read_flp(path)
    except MalformedFLP as exc:
        return RoundTrip(False, f"the writer cannot rewrite this file: {exc}")

    rewritten = flp.to_bytes()
    if rewritten == original:
        return RoundTrip(
            True,
            f"rewrite reproduces the file byte for byte ({len(flp.events)} events)",
            byte_identical=True,
        )

    # Same events, different bytes: usually a varint FL wrote long-form.
    try:
        again = read_flp_bytes(rewritten)
    except MalformedFLP as exc:
        return RoundTrip(False, f"the rewritten file does not parse back: {exc}")
    same = len(again.events) == len(flp.events) and all(
        a.id == b.id and a.payload == b.payload for a, b in zip(again.events, flp.events, strict=True)
    )
    if same:
        return RoundTrip(
            True,
            f"rewrite differs by {abs(len(rewritten) - len(original))} bytes of "
            f"encoding but carries every event unchanged ({len(flp.events)} events)",
        )
    return RoundTrip(False, "the rewritten file's events differ from the original's")


def read_flp_bytes(raw: bytes):
    """``read_flp`` for bytes already in memory."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".flp", delete=False) as handle:
        handle.write(raw)
        name = handle.name
    try:
        return read_flp(Path(name))
    finally:
        Path(name).unlink(missing_ok=True)

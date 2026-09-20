"""Reopening exported MIDI and comparing it to the project it came from.

HARDENING P1.3. A ``.mid`` that exists is not a ``.mid`` that is right, and a
wrong one is invisible until the user drags it into a DAW and hears nothing.
``mido`` is already a dependency and is enough for this: reopen the file, count
the notes, and compare pitches and tick positions with what the project says.

Deliberately not added: ``pretty_midi``. It brings numpy and a tempo model this
does not need.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MidiCheck:
    path: Path
    ok: bool
    detail: str
    note_count: int = 0
    expected_notes: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "file": self.path.name,
            "ok": self.ok,
            "detail": self.detail,
            "notes": self.note_count,
            "expectedNotes": self.expected_notes,
        }


def _note_ons(path: Path) -> list[tuple[int, int, int]]:
    """``(absolute_tick, pitch, velocity)`` for every sounding note-on."""
    import mido

    midi = mido.MidiFile(str(path))
    events: list[tuple[int, int, int]] = []
    for track in midi.tracks:
        tick = 0
        for message in track:
            tick += message.time
            # A note-on with velocity 0 is a note-off by convention.
            if message.type == "note_on" and message.velocity > 0:
                events.append((tick, int(message.note), int(message.velocity)))
    return sorted(events)


def verify(path: Path, expected: list[tuple[int, int, int]]) -> MidiCheck:
    """Compare one exported file against the notes it should contain."""
    path = Path(path)
    if not path.is_file():
        return MidiCheck(path, False, "the file was not written", 0, len(expected))

    try:
        actual = _note_ons(path)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a failure
        return MidiCheck(path, False, f"could not be reopened: {exc}", 0, len(expected))

    if not expected:
        # Nothing to compare against; only report that it reopens.
        return MidiCheck(path, True, f"reopens, {len(actual)} notes", len(actual), 0)

    if len(actual) != len(expected):
        return MidiCheck(
            path, False,
            f"{len(actual)} notes in the file, {len(expected)} in the project",
            len(actual), len(expected),
        )

    if {p for _, p, _ in actual} != {p for _, p, _ in expected}:
        return MidiCheck(
            path, False, "the set of pitches differs from the project",
            len(actual), len(expected),
        )

    if [t for t, _, _ in actual] != [t for t, _, _ in expected]:
        return MidiCheck(
            path, False, "note positions differ from the project",
            len(actual), len(expected),
        )

    if [v for _, _, v in actual] != [v for _, _, v in expected]:
        return MidiCheck(
            path, False, "velocities differ from the project",
            len(actual), len(expected),
        )

    return MidiCheck(
        path, True, f"{len(actual)} notes match the project", len(actual), len(expected)
    )


def reopens(path: Path) -> MidiCheck:
    """The weakest useful check: the file we wrote can be read back.

    Used when the per-file mapping back to source patterns is not to hand. It
    still catches a truncated or malformed write, which is the failure that
    actually happens.
    """
    return verify(path, [])

"""Per-role MIDI export.

One .mid per musical role, at the project's own PPQ and tempo, so the files
drop back into FL (or any DAW) aligned with the source. Note content is copied
exactly - this is an export, not an arrangement.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from prosody_core.model.roles import Role
from prosody_core.model.schemas import Analysis, BeatProject, Note

#: FL key 60 displays as C5; MIDI note 60 is C4. FL's stored number maps
#: directly onto the MIDI note number, so no transposition is applied - only
#: clamping into MIDI's 0-127 range.
MIDI_MIN, MIDI_MAX = 0, 127

ROLE_ORDER: tuple[Role, ...] = (
    Role.CHORDS, Role.MELODY, Role.COUNTER, Role.BASS, Role.KICK,
    Role.SNARE, Role.HATS, Role.PERC, Role.VOCAL, Role.FX, Role.UNKNOWN,
)


def _notes_by_role(
    project: BeatProject, analysis: Analysis
) -> dict[Role, list[Note]]:
    role_of = {
        a.channel: a.role for a in analysis.roles if a.channel is not None
    }
    grouped: defaultdict[Role, list[Note]] = defaultdict(list)
    for pattern in project.patterns:
        for note in pattern.notes:
            grouped[role_of.get(note.channel, Role.UNKNOWN)].append(note)
    return dict(grouped)


def write_role_midi(
    project: BeatProject, analysis: Analysis, out_dir: Path
) -> list[Path]:
    """Write ``MIDI/<nn>_<Role>.mid``. Returns the files created."""
    import mido

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    grouped = _notes_by_role(project, analysis)
    tempo = project.tempo or 120.0
    written: list[Path] = []

    index = 0
    for role in ROLE_ORDER:
        notes = grouped.get(role)
        if not notes:
            continue
        index += 1

        midi = mido.MidiFile(ticks_per_beat=project.ppq or 96)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage("track_name", name=role.value, time=0))
        track.append(
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo), time=0)
        )
        numerator, denominator = project.time_signature
        track.append(
            mido.MetaMessage(
                "time_signature", numerator=numerator or 4,
                denominator=denominator or 4, time=0,
            )
        )

        # Build absolute-time events, then convert to delta times.
        events: list[tuple[int, int, int, int]] = []  # (tick, on/off, key, vel)
        for note in notes:
            key = max(MIDI_MIN, min(MIDI_MAX, note.key))
            velocity = max(1, min(127, note.velocity))
            events.append((note.position, 1, key, velocity))
            events.append((note.position + max(note.length, 1), 0, key, 0))
        # Note-offs before note-ons at the same tick, so repeated pitches retrigger.
        events.sort(key=lambda e: (e[0], e[1]))

        previous = 0
        for tick, kind, key, velocity in events:
            delta = tick - previous
            previous = tick
            track.append(
                mido.Message(
                    "note_on" if kind else "note_off",
                    note=key, velocity=velocity, time=delta,
                )
            )

        path = out_dir / f"{index:02d}_{role.value.capitalize()}.mid"
        midi.save(str(path))
        written.append(path)

    return written

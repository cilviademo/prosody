# project.json (BeatProject)

Normalised, backend-independent view of one `.flp`. Written to
`out/<slug>/DATA/project.json`. Defined in `prosody_core/model/schemas.py`;
changing it requires an ADR.

`schema_version` is `"1.0"`.

## Top level

| Field | Type | Notes |
| --- | --- | --- |
| `id` | str | sha256 of the source `.flp` bytes. The project's identity everywhere. |
| `source_path` | str | Absolute path read from. Never written to. |
| `source_bytes` | int | Size on disk. |
| `parsed_at` | datetime | UTC. |
| `backend` | str | e.g. `pyflp-2.2.1+compat`. `+compat` means ADR-0002's shim was active. |
| `fl_version` | str \| null | From the file header. `null` means absent, not old. |
| `fl_build` | int \| null | |
| `tempo` | float \| null | BPM. `null` when no tempo event was found. |
| `ppq` | int | Ticks per quarter note. Defaults to 96. |
| `time_signature` | [int, int] | Defaults to 4/4. |
| `length_ticks` | int | Longest playlist extent, or the longest pattern when there is no playlist. |
| `title` | str \| null | |
| `key_guess` | object \| null | Not implemented; always `null`. |
| `unknown_event_ids` | int[] | Event ids PyFLP had no model for. Recorded so the writer can prove it preserved them. |
| `parse_warnings` | ParseWarning[] | See below. |

Derived (properties, not serialised): `note_count`, `length_bars`,
`duration_seconds`. `duration_seconds` is `null` when tempo is unknown rather
than guessed.

## Collections

**`channels[]`** — `index`, `name`, `kind`
(`plugin|sampler|layer|automation|unknown`), `plugin`, `sample_path`,
`mixer_track`, `enabled`.

**`patterns[]`** — `index` (FL's 1-based internal id), `name`, `length_ticks`,
`notes[]`. A pattern with no explicit length takes the extent of its notes.

**`notes[]`** — `channel`, `position`, `length` (ticks), `key` (0–131, FL's
numbering where 60 is C5), `velocity` (0–127), `pan`.

**`mixer[]`** — `index`, `name`, `effects[]`, `routes_to[]`. `effects` is empty
when the project carries no mixer `Params` event; that is reported as an INFO
note, not a failure.

**`arrangements[]`** — `index`, `name`, `tracks[]`, `clips[]`, `markers[]`.
FL supports several; all are read.

**`clips[]`** — `track`, `kind` (`pattern|channel`), `pattern` or `channel`,
`start_ticks`, `length_ticks`. A model validator rejects a clip whose target does
not match its kind.

**`samples[]`** — `path`, `found` (resolved against this machine's filesystem at
parse time), `used_by_channels[]`.

**`plugins[]`** — `name`, `used_by_channels[]`. Presence in this list says
nothing about whether the plugin is installed.

## ParseWarning

`code`, `message`, `severity` (`info|warning|error`).

- `error` — the file is damaged.
- `warning` — we failed to read something we expected to read.
- `info` — the file genuinely does not describe this. Does not degrade health.

Warnings are deduplicated by `(code, message)`: a 100-channel project emits one
copy of a repeated notice, not a hundred.

## Round-tripping

`BeatProject.model_validate(json.loads(...))` reconstructs an equal object.
Asserted by `test_written_project_json_round_trips_through_the_model`.

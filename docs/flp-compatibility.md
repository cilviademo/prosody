# FLP format compatibility

What is verified, what is assumed, and what has not been tested. Everything here
was measured on this machine against PyFLP 2.2.1 unless marked otherwise.

## Container format (verified)

```
FLhd | u32 size = 6 | i16 format | u16 channel_count | u16 ppq
FLdt | u32 size    | events...
```

Event encoding — the id selects the payload width:

| id range | payload |
| --- | --- |
| 0–63 | 1 byte |
| 64–127 | 2 bytes (LE) |
| 128–191 | 4 bytes (LE) |
| 192–255 | varint length, then that many bytes |

Text events are UTF-16LE from FL 11.5 onward and ASCII before. **`FLVersion`
(id 199) is always ASCII**, because the parser reads it to decide the encoding of
everything after it. Getting this wrong is the first thing that breaks a
hand-written FLP.

Valid PPQ values: 24, 48, 72, 96, 120, 144, 168, 192, 384, 768, 960.

Notes are 24-byte records; playlist items are 32 bytes (60 from FL 21). Playlist
track indices are stored reversed from 499. A playlist item references a pattern
as `pattern_base (20480) + pattern_iid`; a lower value is a channel clip.

Note keys are 0–131. PyFLP exposes them formatted as names
(`NAMES[k % 12] + str(k // 12)`, sharps only), so `60` reads back as `"C5"`. The
adapter reads the raw struct field and only parses the name as a fallback.

## Parser: PyFLP 2.2.1

### Blocking incompatibility, with a shipped workaround

**PyFLP 2.2.1 cannot parse any `.flp` on Python 3.11, 3.12 or 3.13.** Full
analysis and the four-line fix are in
[ADR-0002](adr/ADR-0002-pyflp-enum-compat.md). `flpf doctor` reports whether the
shim is active.

### Fragilities found while building fixtures

Each of these is a case where PyFLP raises instead of returning empty. The
adapter converts all of them into `ParseWarning`s.

| Condition | PyFLP behaviour | Our behaviour |
| --- | --- | --- |
| Project with no channels | `KeyError: ChannelID.New` when iterating channels | `channels` warning; header, tempo, patterns still returned |
| Channel with no `GroupNum` event | `KeyError: ChannelID.GroupNum` | warning, channel list degrades |
| No `DisplayGroup` events at all | `IndexError` indexing `groups[groupnum]` | warning, channel list degrades |
| Insert slots without a `MixerID.Params` event | `KeyError: 'params'` | INFO note: effect chains not describable from this file |
| Last arrangement not terminated by `ArrangementsID.Current` | arrangement silently not yielded | not detectable; see UNVERIFIED |

The last row is worth emphasising: it fails **silently**. A file whose event
stream ends immediately after the playlist yields zero arrangements with no
error. Whether FL Studio ever writes such a file is unverified.

### Write support

**Completely unverified.** `pyflp.save()` has not been run against any real
project. One thing is visible from reading the source without running it:

```python
num_channels = len(project.channels)
header = FLP_HEADER.pack(b"FLhd", 6, project.format, num_channels, project.ppq)
```

The header's `channel_count` is recomputed from the parsed channel list rather
than preserved from the original header. For any project where those differ, a
save is not byte-identical. Whether that matters to FL Studio is unknown.

This is EXECUTE.md spike T2 and it gates both the writer (Phase 5) and the S1
stem strategy (SPEC.md section 5 kill criterion: "PyFLP save fails or changes
the project on ≥ 2 of 25 corpus files").

## FL version coverage

| FL version | Files tested | Result |
| --- | --- | --- |
| 21.2.3 (synthetic) | 6 fixtures | parse |
| everything else | 0 | **untested** |

No real FL-saved project has been parsed. The corpus is empty on this machine.
This table is the honest state of SPEC.md's ≥ 80% parse-rate criterion: not
failed, not passed, **unmeasured**.

## Not yet examined

Automation clips, audio clips, time markers on real projects, multiple
arrangements, nested project folders, Patcher, layered channels, unusual
routing, projects above ~50 MB.

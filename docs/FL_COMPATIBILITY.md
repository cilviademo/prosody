# FL Studio compatibility

One row per version **actually tested**, with the date it was tested. A version
that is not listed has not been tried, and Prosody makes no claim about it.

This table is empty of real rows on purpose. Writing optimistic entries here
would be the same mistake as marking an untested acceptance step as WORKING.

| FL version | Parse | Write derivative | Opens generated `.flp` | Render | MIDI export | ZIP export | Stems | Tested on |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20.9.2.2963 | pass¹ | — | — | fail² | — | — | — | 2026-09-22, studio PC, release v0.1.0 |
| 2026 (loop_test.flp) | fail³ → fallback untested | — | — | fail² | — | — | — | 2026-09-22, studio PC, release v0.1.0 |

¹ Parsed (90 channels, 127 mixer tracks, 260 clips, 39 missing samples) but
reported 0 patterns / 0 notes / 1 plugin for a session whose channels are named
after generator plugins. Unverified against what FL shows — P1.2 in
`TESTING_HANDOFF.md`. Treat the counts as unconfirmed until FL's own pattern
count is compared.

² Not FL's fault: the render command never named the project. Fixed; not yet
re-run on the studio PC.

³ PyFLP 2.2.1 raised a UTF-16 decode error whose payload contained several
whole events joined together — a fault in PyFLP's string layer, above the
event splitter. The file carried `DisplayGroupID.Name` (231) events
("Unsorted", "Loop Starter #1"), which PyFLP knows. Prosody now falls back to
its own event reader when PyFLP raises; that fallback is verified on a
2026-shaped fixture and on a reproduction of the exception, **not yet on the
real file**. `flpf events loop_test.flp` (or Copy event inventory in the app)
produces the inventory that will say what else FL 2026 writes.

## What has been tested instead

Synthetic projects built by `tests/fixtures/flp_builder.py`, which writes the
`FLhd`/`FLdt` structure by hand to the format notes in
`docs/flp-format.md`. Those cover the parser and the writer thoroughly — 650
tests — and cover FL Studio itself not at all.

The gap matters in one specific direction: a real project carries plugin state
blobs, automation, mixer routing and sample references that a synthetic fixture
does not. The writer preserves unknown events verbatim precisely so those
survive without being understood, but "preserved byte for byte" has only been
demonstrated against fixtures.

## How to fill a row in

1. Open the project in FL Studio first and note what it contains.
2. Drop it into Prosody. Compare the reported tempo, patterns, channels,
   plugins and samples against FL.
3. Build with Preserve Composition.
4. Open the generated `.flp` in FL Studio. Check that every channel, pattern,
   plugin preset and mixer insert is intact, and that only the playlist differs.
5. Render. Confirm the duration matches the planned bar count.
6. Record the result, with the date and the exact FL version from
   Help → About, and put any screenshots under `docs/evidence/<date>/`.

Mark a cell `partial` with a footnote rather than `yes` if anything needed a
workaround. A row with `yes` in it is a promise to the next person who reads it.

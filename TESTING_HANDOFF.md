# TESTING_HANDOFF.md — Prosody local testing, 2026-09-22

Session summary: the release build launches and runs, parses an FL 20.9 project,
detects roles, and shows Diagnostics. It cannot parse projects saved by the FL
version actually installed on this PC (FL Studio 2026), did not auto-detect that
FL install, and its command-line render test produced no file. Nothing here is
a redesign; fix in the order below and re-verify with the steps in section 5.

Read this file, then work P0 → P1 → P2. After each fix, update
CURRENT_STATUS.md and append results to section 6 of this file.

---

## 1. Test environment (facts, not assumptions)

| Item | Value |
| --- | --- |
| Machine | Studio PC, Windows, user `marcm` |
| FL Studio | **FL Studio 2026**, `C:\Program Files\Image-Line\FL Studio 2026\FL64.exe` |
| Second FL version seen in files | 20.9.2.2963 (a project from the other PC) |
| Desktop / Documents | OneDrive-redirected (`C:\Users\marcm\OneDrive\Desktop\…`) |
| Export folder set by user | `C:\Users\marcm\OneDrive\Desktop\Prosody` (see P1.4) |
| `where.exe python` | returns `…\WindowsApps\python.exe` — the Microsoft Store stub, not a real install |
| node / cargo / git on PATH | none |
| Clean-account (`prosody-test`) run | **not yet performed** — everything below is from the main account |
| Round-trip spike (Phase 0 T2) | **still not run** — Health check shows `write_compatibility ?` |

Test files:
- `8-27-23 #1 (Tony x Eddie).flp` — FL 20.9, 156 BPM, 130 bars, 260 playlist
  clips, 90 channels, 127 mixer tracks, 39 missing samples (they live on the
  other PC). Parses. Reported 0 patterns / 0 notes / 1 plugin (see P1.2).
- `loop_test.flp` — new 4-bar loop created and saved with FL 2026 on this PC.
  **Fails to parse** (P0.1). FL opens it fine.

---

## 2. P0 — blocks the core workflow

### P0.1 Parser fails on FL Studio 2026 projects
Error shown in UI on drop:
```
This project could not be read: cannot use encoding 'utf-16-le' to decode
b'n?\xe7 L\x00o\x00o\x00p\x00 \x00S\x00t\x00a\x00r\x00t\x00e\x00r\x00\x00#\x001\x00
\x00\x00\xe7\x12U\x00n\x00s\x00o\x00r\x00t\x00e\x00d\x00\x00\x00\x00\x92\xff\xff\xff\xff\xd8\x00A\x01\x00\xe0\xb8\x02…'
```
Reading: the previous event's length was mis-measured, the cursor ran into a
text event (`\xe7` + varint length 0x12 = "Unsorted", and "Loop Starter #1"
before it), and an odd-length slice was decoded as UTF-16. Event ID 0xE7 (231)
has no definition in the bundled PyFLP. This is the Phase 0 parse-rate risk,
now confirmed on the user's primary FL version.

Fix, in order:
1. **Fail soft before anything else.** Read the FL version from the .flp
   header before full parse (it is in the first bytes and always readable).
   Skip any unknown event ID ≥ 192 by its varint length prefix instead of
   raising. Decode text with `errors="replace"` and emit a parse warning.
   The UI shows: "Saved with FL Studio 2026.x. Prosody's parser fully
   supports up to 20.9; results may be incomplete." Raw exception goes under
   Diagnostics only.
2. **Diff the event streams** of `loop_test.flp` (2026) and the 20.9 file.
   List every event ID present in the 2026 file that PyFLP lacks. Add
   definitions for the ones that carry data the app needs (playlist track
   groups are the first suspect, given "Unsorted"); record the rest in
   `docs/FL_COMPATIBILITY.md` as skipped.
3. **Evaluate flpdiff** on `loop_test.flp` as the read backend for newer
   files, behind the existing Backend protocol. Report which of the two
   backends yields correct tempo, pattern count, note count and playlist
   for both test files.
4. Add both files (or anonymized copies) to `tests/corpus/` fixtures; the
   corpus tier must include at least one project per FL version the user
   has: 20.9 and 2026.

Acceptance: `loop_test.flp` opens in Prosody with correct BPM, ≥ 1 pattern
with notes, roles assigned, and Arrange enabled.

### P0.2 FL command-line render produces no output
Settings → Test result: `FL Studio exited cleanly but produced no files (exit 0)`.
FL launched and quit; no file appeared where Prosody expected one.

Fix:
1. Read the adapter's logged command line from `core.log` for this Test
   and compare with what FL 2026 documents (open FL, F1, search "command
   line"; the switch set or output naming may have changed since 20.x).
2. Reproduce outside the app with the user's loop:
   `& "C:\Program Files\Image-Line\FL Studio 2026\FL64.exe" /R /Ewav "<path>\loop_test.flp"`
   and the bare `/R "<path>"` form. Determine (a) whether FL writes next to
   the .flp rather than to a temp dir, (b) the filename it chooses, (c)
   whether a dialog interrupts (first-run, audio device, news).
3. Fix the adapter: correct switches for 2026, look for output where FL
   writes it, then move it; verify by file existence + mtime later than
   launch + duration check. Make the bundled Test project one that FL 2026
   opens (a minimal project saved by a recent FL, not a hand-built stub).
4. Version-aware switch table in the adapter keyed by the major FL version
   read from `FL64.exe`'s file version info.

Acceptance: Test passes on FL 2026 and writes a WAV of the expected length;
the exact command is visible in Diagnostics.

### P0.3 FL Studio auto-detection misses the 2026 install
Message: `not in the registry, the default install folders, or PATH`.
Actual location: `C:\Program Files\Image-Line\FL Studio 2026\FL64.exe`.

Fix: enumerate `C:\Program Files\Image-Line\*\FL64.exe` and the
`(x86)` variant with a glob instead of a fixed list of version names; walk
`HKLM\SOFTWARE\Image-Line` and `HKCU\SOFTWARE\Image-Line` recursively for
any install-path value; prefer the highest version by file version info.
Ask the user to paste the output of
`Get-ChildItem "HKLM:\SOFTWARE\Image-Line" -Recurse | Select-Object Name`
if the registry layout for 2026 is unclear.

Acceptance: fresh settings, launch, FL detected without user action.

---

## 3. P1 — truth, correctness, safety

### P1.1 Header shows "FL Studio ready" after a failed Test
The status pill turned green once a path was set, even though Test failed.
"Ready" must require a passing Test in this session (or a cached pass with
unchanged exe hash). Otherwise show "FL Studio configured, render untested"
or "render test failed".

### P1.2 Verify the 20.9 file reading (possible parser gap)
Prosody reported for the Tony x Eddie project: 0 patterns, 0 notes,
Plugins 1, yet channels are named `Ripchord`, `Lounge Lizard EP-4`
(generator plugins). Either the project truly has no MIDI patterns (audio-clip
session) and one generator, or PyFLP is dropping patterns/plugins on 20.9.
User action: open the file in FL and report the pattern count and generator
list. Agent action: compare against the parse; if FL shows patterns, treat as
P0 and fix.

### P1.3 Health-check and Diagnostics hygiene
- `flp_readable … parsed by pyflp-unknown+compat` — PyFLP version metadata
  not bundled; collect `importlib.metadata` for pyflp in the PyInstaller spec.
- `write_compatibility ? … Phase 0 spike T2 not yet run` — run the round-trip
  (parse → save → parse → structural diff) on every corpus file and on
  `loop_test.flp` once P0.1 lands; write the verdicts to
  `docs/FL_COMPATIBILITY.md` and change this row to ok/fail per file.
- Low-confidence channel table runs name and status together
  (`Volume multiplierunknown  0.00`); pad columns or render as a table.
- `plugins_available ?` says "not checkable without FL Studio on this machine"
  while FL is configured; the check should use the configured install.

### P1.4 Export folder on OneDrive
User set exports to a OneDrive-synced Desktop folder. Two consequences to
handle, not forbid: (a) OneDrive can hold locks during sync, so `os.replace`
to the final name can raise `PermissionError` — implement the retry/next-
version behavior from HARDENING P0.4 and test it by exporting into that
folder; (b) show a one-time notice when the chosen export folder is inside a
OneDrive/Dropbox/iCloud path ("stems can be large and sync will lock files;
a local folder is recommended"), with a "use C:\Prosody\Exports" shortcut.
Default export location should avoid Documents when Documents is
OneDrive-redirected (check the known-folder path, not the literal string).

### P1.5 Missing-samples flow
39 missing on the 20.9 project (samples live on another PC). Current message
is good. Add: "Locate folder…" that scans a user-chosen root for matching
filenames and marks candidates RELOCATED pending confirmation; never rewrite
source references (HARDENING P1.6). Extract on such a project should still
produce ZIP + MIDI + project.json and mark WAV as "incomplete: N samples
missing", not fail.

### P1.6 Not-arrangeable projects
Arrange correctly disabled with "Needs at least one pattern with notes" on the
audio-clip session. Keep. Add a Stem Mode hint: "This project is audio-clip
based; arrangement from playlist audio clips is planned" so the user knows it
is a capability gap, not a file problem.

---

## 4. P2 — after P0/P1 verified

- Run the **clean-account test** (`prosody-test`, no dev tools) per RELEASE.md
  §10, with `loop_test.flp` once it parses. Not yet done.
- Run the **Windows Sandbox** first-run test (`test\sandbox\prosody.wsb`) for
  FL-absent and WebView2-absent paths.
- Portable-mode check (`portable.flag` → `Data\` beside the exe).
- Offline check with Rules Only.
- Installer install/uninstall cycle.
- Update `docs/FL_COMPATIBILITY.md` with rows for 20.9 and 2026: parse,
  write, open generated, render, MIDI export, ZIP export, stems.

---

## 5. Verification script (user runs after each fix batch)

1. Launch release build from outside the repo. FL auto-detected (P0.3).
2. Settings → Test passes; header shows ready only now (P0.2, P1.1).
3. Drop `loop_test.flp` (FL 2026): parses, correct BPM, patterns > 0,
   roles > 0, Arrange enabled (P0.1).
4. Drop the 20.9 file: values match what FL shows (P1.2); pyflp version
   shown (P1.3).
5. R&B → Preserve Composition → timeline → Build on `loop_test.flp`:
   Full.wav has the planned duration; MIDI reopens; validation level shown;
   `.flp` output or Arrangement Pack message.
6. `Get-FileHash` on the source before and after step 5: identical.
7. Export into the OneDrive folder while OneDrive is syncing: no crash;
   locked-destination path handled (P1.4).
8. Restart Prosody: Library and settings persist.

---

## 6. Results log (append per run)

| Date | Build | Step | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-09-22 | v0.1.0 | Launch (main account) | PASS | native window, no console |
| 2026-09-22 | v0.1.0 | FL auto-detect | FAIL | 2026 install not found |
| 2026-09-22 | v0.1.0 | Manual FL path + Test | FAIL | exit 0, no file |
| 2026-09-22 | v0.1.0 | Parse FL 20.9 project | PASS (unverified counts) | see P1.2 |
| 2026-09-22 | v0.1.0 | Parse FL 2026 loop | FAIL | utf-16 decode error |
| 2026-09-22 | v0.1.0 | Arrange gating | PASS | correctly disabled on 0-pattern file |
| 2026-09-22 | v0.1.0 | Clean-account run | NOT RUN | |
| 2026-09-22 | v0.1.0 | Round-trip spike | NOT RUN | |
| 2026-09-22 | main (post-handoff) | P0.3 discovery | FIXED, verified on a synthetic Program Files tree | globs `Image-Line\*`, walks the registry, prefers the newest by file version; `FL Studio 2026` chosen over 21/2024/2031-style names; the registry walk needs a real run to confirm |
| 2026-09-22 | main (post-handoff) | P0.2 render command | ROOT CAUSE FOUND, FIXED, verified against a stand-in FL | the old command never named the project (`/R<output-stem> /Ewav`); now `/R /E<fmt> <project.flp>`, output watched beside the project and moved, WAV length checked, exact argv shown in Settings. **Not yet re-run on FL 2026** |
| 2026-09-22 | main (post-handoff) | P0.1 FL 2026 parse | FALLBACK BUILT, verified on a 2026-shaped fixture and on the reproduced exception | PyFLP failure now falls back to Prosody's own event reader, which agrees with PyFLP on every fixture; version read from the header first; raw exception under Parser notes, not the headline. **Not yet run on `loop_test.flp`** — `flpf events loop_test.flp` or Copy event inventory finishes the diagnosis |
| 2026-09-22 | main (post-handoff) | P1.1 ready pill | FIXED | green only after a passing Test against the same executable (size+mtime fingerprint) |
| 2026-09-22 | main (post-handoff) | P1.3 pyflp version in bundle | FIXED | `copy_metadata("pyflp")` in the spec; visible in the next release build |

## 7. Final response format after this handoff is worked

1. P0.1 / P0.2 / P0.3: fixed or not, with the verification-script step result
2. Which backend reads FL 2026 files, and the parse counts for both test files
3. The exact FL 2026 render command now used
4. Round-trip verdicts per corpus file
5. Updated CURRENT_STATUS.md summary (WORKING / PARTIAL / NOT YET WORKING)
6. Remaining highest-priority limitation

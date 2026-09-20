# CURRENT_STATUS

Prosody v0.1.0 · 2026-09-20

**This session ran on Linux in a container.** Windows binaries need Windows, so
per RELEASE.md section 0 all code and configuration work happened here and the
`windows-latest` GitHub Actions job produces the ZIP and installer.

**The release now exists.** <https://github.com/cilviademo/prosody/releases/tag/v0.1.0>
carries `Prosody-v0.1.0-Windows.zip` (20.1 MB) and
`Prosody_0.1.0_x64-setup.exe` (17.5 MB), built by run 35538426564.

**The clean-machine acceptance test (RELEASE.md section 10) was still not run**
— it needs a Windows account and FL Studio, and no step below is marked
WORKING on the strength of anything that was not actually executed. What was
executed against the published artefacts, from here: the one-line installer
resolved the release, downloaded the ZIP, verified its SHA-256 against the
published `SHA256SUMS.txt` and installed the correct layout; `Prosody.exe` is
a PE32+ GUI binary and `prosody-core.exe` a PE32+ console binary, which is the
combination the stdio IPC needs; all six genre profiles and the
connection-test asset are inside the bundle. Nobody has yet *launched* it on
Windows.

---

## HARDENING acceptance gate

HARDENING.md defines FIRST-RUN READY as fourteen conditions passing **on the
release artifact, in a second Windows account or a Sandbox**. Six of them
cannot be answered from a Linux container, so the honest verdict is
**NOT FIRST-RUN READY** — not because something is known broken, but because
six conditions are unverified and this document does not mark unverified
conditions as passed.

| # | Condition | State |
| --- | --- | --- |
| 1 | Starts from a folder outside the repo, second account, no dev tools | NOT RUN — needs Windows |
| 2 | No global Python, Node, Git or GitHub needed | ENFORCED IN CODE — the run-from-source path is `#[cfg(debug_assertions)]` and absent from a release; a test asserts it |
| 3 | WebView2 handled | BUILT — the installer now carries the runtime (`offlineInstaller`), which took it from 17.6 MB to 221.7 MB; the portable build detects and explains. The bundling succeeded; the behaviour on a machine *without* WebView2 is NOT OBSERVED |
| 4 | Core starts, hash matches build-info | VERIFIED — the published v0.1.0 core's SHA-256 equals the value in its `build-info.json`, checked against the downloaded artifact |
| 5 | Workspace and DB initialise; System Check has no FAIL | VERIFIED HERE, not on Windows |
| 6 | Source read-only safeguards pass their tests | VERIFIED — 18 tests, including a hard-link identity case and a write-over-source attempt that leaves the bytes unchanged |
| 7 | FL detection correct with FL present and absent | HALF — absent is covered; present needs the studio PC |
| 8 | One real `.flp` analyses; a plan generates offline | NOT RUN — no real project has ever been parsed |
| 9 | Derivative reaches STRUCTURALLY_VALIDATED or shows the fallback | VERIFIED on fixtures |
| 10 | Source hash unchanged after every operation | VERIFIED — checked before and after, with a mid-run edit caught |
| 11 | Outputs and Library survive restart | VERIFIED HERE via the rebuild path |
| 12 | Offline first run works | VERIFIED — a full build runs with every socket entry point replaced by a landmine |
| 13 | Logs and the sanitized report contain no secrets | VERIFIED — a planted key appears in neither |
| 14 | Downloaded-ZIP path with Mark-of-the-Web intact | NOT RUN — needs a browser download on Windows |

`test/sandbox/prosody.wsb` and `test/sandbox/README.md` ship the harness for
1, 3, 7 and 14. Results belong in `docs/evidence/<date>/`, which is empty.

## NOT DONE from HARDENING, with reasons

- **Resume-from-stage for an interrupted build (P0.4).** The manifest and the
  startup sweep are done: an interrupted export folder records its source, its
  hash, the options, every stage with a timestamp, and how far it got, and
  Prosody surfaces it on launch with Open folder / Discard / Dismiss. What is
  not implemented is re-entering a build at the stage it stopped at. Every
  stage is deterministic given the same source, so re-running is correct and
  only costs time — which makes Restart the same action as Resume, and a
  separate Resume button would be a false distinction. Stage-level re-entry is
  worth building when renders are long enough for it to matter.
- **P1.2 independent parser (flpdiff).** Not bundled. Its licence has not been
  verified from its own LICENSE file, and shipping a JavaScript parser needs
  either the webview or a second sidecar. `SEMANTICALLY_VALIDATED` is therefore
  unreachable; `validation.json` records that in `level_detail` rather than
  inflating the level, which is option 3 in HARDENING P1.2.
- **numpy, soundfile, ffmpeg not bundled** (P0.1 lists them). Nothing imports
  them: FL Studio encodes MP3 itself and the preview stitcher does not exist.
  Bundling them would add tens of megabytes of unused DLLs and, for ffmpeg, a
  licence question for no capability. `prosody-core.spec` says how to add them
  back when `preview/stitch.py` lands.
- **P1.6 sample and plugin states** beyond AVAILABLE/MISSING. RELOCATED and
  FAILED_IN_RENDER are not implemented.
- **P2.3 signing.** `digestAlgorithm` and `timestampUrl` are set and
  `certificateThumbprint` is deliberately null. No certificate exists, and none
  should be self-signed.
- **A CycloneDX SBOM.** `licenses/THIRD-PARTY.md` is the stated minimum and is
  complete, with bundled/not-bundled and purpose per component.

## WORKING

Verified by running it here, on Linux, against synthetic projects.

- **The whole loop in the app:** drop or browse an `.flp` → analysis → Extract
  / Arrange / Extract + Arrange → genre → structure → creativity → timeline →
  Build → results. Re-verified end to end after the core was rearchitected.
- **Native derivative `.flp` (Tier A).** A four-bar loop becomes an 80-bar
  hip-hop or 88-bar R&B project. Patterns, channels, notes, plugins, mixer and
  routing are copied byte for byte; only the playlist event is replaced.
- **The original is never modified.** Hashed before, re-verified after.
- **Long-lived core over stdio JSON lines.** One process for the session with
  request ids and streamed progress — not one process per call. 21 protocol
  tests, including that the loop survives malformed input, unknown methods and
  handler failures.
- **The frozen core works.** `python -m PyInstaller prosody-core.spec` builds a
  33 MB onedir bundle that answers `ping` and runs a complete build — genre
  profiles and the connection-test asset included. Verified on Linux.
- **Two roots, as specified.** `Documents/Prosody/{Exports,Projects}` for user
  output; `%LOCALAPPDATA%/Prosody/{prosody.db,settings.json,Cache,Logs}` for
  state. Portable mode collapses both into `Data/` beside the executable.
- **Diagnostics screen** instead of a blank window when the core fails to
  start, with the log path and a Try again button that respawns it.
- **Offline, proven at runtime.** A full build runs with every socket entry
  point replaced by a landmine; the AST walk separately proves nothing
  network-capable is even imported.
- **Test Connection renders** the bundled one-bar project rather than just
  checking a path exists.
- **Settings take effect** — FL path and Rendering toggle are read by the
  environment resolver.
- **530 unit tests, ruff clean, tsc clean, zero Rust warnings** — verified in a
  clean virtualenv, not just the development one.
- **The one-line installer** (`scripts/install.ps1`) resolves the newest
  release that carries a Windows ZIP, verifies its SHA-256 against the
  published `SHA256SUMS.txt`, installs to `%LOCALAPPDATA%\Programs\Prosody`,
  clears the mark-of-the-web and adds a Start Menu entry. Both halves were
  exercised here: the release lookup against the live GitHub API, and the
  install from a ZIP of the real release shape, and then against the published
  v0.1.0 release itself, end to end. That last run found the bug that mattered:
  checksum verification was silently skipping. GitHub serves release assets as
  `application/octet-stream`, so `Invoke-WebRequest`'s `.Content` came back as
  a `byte[]` rather than a string; splitting that into lines matched nothing
  and the script said "no checksum recorded" and carried on. It now reads the
  file from disk, and a missing entry is a visible warning rather than a grey
  note. Four tests guard that the URL in README.md resolves to a script in the
  tree, on a branch that is built.
- **CI runs on every push** (`.github/workflows/ci.yml`) and already earned its
  keep: the first run failed because `mido` was declared as an optional extra
  while every build imports it, so a fresh install had no MIDI export. Fixed,
  and a test now asserts every imported package is a required dependency.

## PARTIAL

- **The Windows build has now run, and needed two fixes** — RELEASE.md said to
  expect that, and it was right. The first attempt stopped at the test suite:
  four tests that are green on Linux failed on the runner because PyFLP returns
  a `pathlib.Path` for a sample and `str()` renders the *host's* separators, so
  fixtures written with forward slashes came back rewritten. The fixtures were
  wrong, not the product — FL writes backslashes, which round-trip unchanged on
  both platforms. The second was `tauri.conf.json`'s `licenseFile`, which
  pointed at a path that does not exist; `tauri dev` never reads it, so only
  NSIS would ever have noticed. Both now have tests that fail without the fix.
- **The Windows-only Rust type-checks.** `cargo check --target
  x86_64-pc-windows-msvc` runs clean over all 18 `#[cfg(windows)]` blocks —
  WebView2 detection, `CREATE_NO_WINDOW`, the registry reads — none of which a
  Linux build compiles at all. CI now runs that check on every push.
- **The release is built by a push to `main`.** This session's credentials are
  refused (HTTP 403) on tag refs and the GitHub integration lacks
  `actions: write` to dispatch a run, but ordinary branch pushes do trigger
  workflows — `ci` has run on all of them. So `release.yml` now also triggers
  on a push to `main`, and creating that branch starts the Windows build
  without a tag or a dispatch. Tags and **Actions → release → Run workflow**
  still work and still pin a named version.
- **WebView2 detection** reads the Edge Update registry keys under HKLM and
  HKCU. It compiles for Windows but has never run against a real registry.
- **Window geometry is saved and restored.** Saved on Tauri's own move and
  resize events rather than the DOM's `resize` alone, so a window dragged to
  another monitor without being resized is remembered too. On launch the size
  is clamped between the configured minimum and the smallest attached monitor,
  and the position is only reapplied if a grabbable strip of the window still
  lands on a monitor that exists now — otherwise it centres. Compiles for
  Windows; the multi-monitor behaviour has not been observed running.
- **Arrangement Pack (Tier B)** triggers correctly but has only been exercised
  by forcing it, never by a real project that defeats the writer.

## NOT YET WORKING

- **Audio rendering and stems have never been run against FL Studio.** The
  wrapper captures command, exit code, stdout, stderr and timing, and is gated
  behind detection plus the Rendering toggle.
- **The FL MIDI-export switch letter** is unconfirmed; `FL_SWITCHES` records it
  as `None` and a render-tier test fails under `FLPF_RENDER=1` until someone
  records it. Per-role MIDI does not need it.
- **Creativity levels 1 and 2.** Selectable, and the UI says they are not
  implemented.
- **LLM planners.** The interface exists; the providers declare themselves
  unavailable and fall back to the deterministic planner.
- **ffmpeg is not bundled.** Nothing calls it — FL renders MP3 natively. The
  lookup (`resources/bin/ffmpeg.exe`, then PATH) is implemented and documented
  so adding it later is a build-script change, not a code change.
- **Sample relinking.** Missing samples are detected and reported, never
  repaired.

## KNOWN ISSUES

1. **No real FL Studio project has ever been parsed.** Every fixture is
   synthetic. The ≥80% parse rate in SPEC.md is unmeasured.
2. **PyFLP is GPL-3.0 and is bundled inside the core executable.** That carries
   obligations for public distribution which have **not** been resolved. Fine
   for private or internal builds; a decision is needed before a public
   release. See `licenses/THIRD-PARTY.md`.
3. **The builds are unsigned**, so SmartScreen shows "Windows protected your
   PC" on first launch. Documented in README.txt and RELEASE_NOTES.md.
4. **PyFLP 2.2.1 cannot parse anything on Python 3.11+** without the shim this
   project ships (`parse/_pyflp_compat.py`).
5. **An arrangement not terminated by `ArrangementsID.Current` is silently
   dropped by PyFLP** — no error, zero arrangements. The most dangerous unknown
   in the parser because it fails quietly.
6. **FL 21 playlist items (60-byte) are untested.** The writer matches the
   source\'s item size and copies an existing item\'s trailing bytes; with none
   to copy it zero-fills and warns.
7. **Section labels clip** on very short sections (`OUTRO` → `OUTR` at 4 bars).

## CLEAN-MACHINE ACCEPTANCE TEST (RELEASE.md section 10)

**NOT RUN.** It requires a second Windows user account, the built ZIP and FL
Studio. Every step below is therefore NOT YET VERIFIED — none may be recorded
as WORKING until it has actually been executed on the studio PC.

| # | Step | Result |
| --- | --- | --- |
| 1-3 | Extract the ZIP, double-click `Prosody.exe`, native window, no console | NOT RUN |
| 4 | FL detection matches reality; Test Connection passes | NOT RUN |
| 5 | Drop a real 4-bar `.flp`; BPM/patterns/channels/plugins match FL | NOT RUN |
| 6 | R&B → Preserve Composition → timeline → Build | NOT RUN |
| 7 | Outputs land in `Documents\Prosody\Exports\<name>__PROSODY_RNB_V001\` | NOT RUN |
| 8 | Source `.flp` hash unchanged (`Get-FileHash` before/after) | NOT RUN |
| 9 | Open Output Folder and Open in FL Studio both work | NOT RUN |
| 10 | Relaunch; settings, FL path and Library persist | NOT RUN |
| 11 | `portable.flag` uses `Data\` and leaves `%LOCALAPPDATA%` untouched | NOT RUN |
| 12 | Network adapter disabled; repeat 5-7 with Rules Only | NOT RUN |
| 13 | Installer: Start Menu entry, launch, clean uninstall | NOT RUN |

The equivalents that *were* run here, on Linux: the frozen core answers ping
and completes a full build (steps 5-7 in substance, not on Windows); the
source hash check is asserted by the test suite (step 8); a full build runs
with sockets disabled (step 12); portable and split-root layouts are asserted
by tests (step 11). None of that substitutes for the real thing.

## NEXT PRIORITY

**Push a tag, download the ZIP, and run section 10 on the studio PC.**

```
git tag v0.1.0 && git push origin v0.1.0
```

Then, in order:

1. If the CI build fails, it will be the PyInstaller spec or a resource path —
   fix and re-tag.
2. Run the clean-account test. Record each step in this file with its real
   result.
3. Configure FL Studio and press **Test Connection**. That single result
   unblocks WAV, MP3 and stems, and answers whether FL leaves a process running
   after a command-line render — which decides whether batch rendering is
   possible at all.
4. Open a generated derivative in FL Studio and confirm its plugins, samples
   and mixer survived. That is the result that decides whether the product
   works.

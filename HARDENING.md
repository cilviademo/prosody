# HARDENING.md — Prosody first-run hardening pass

Goal: a fresh Windows machine launches the release artifact, and Prosody
accurately reports what works, what doesn't, and why, with no Python, Node,
Rust, Git, GitHub or terminal. No new product features. No redesign. Fix what
you find, prove it with the tests below, and end with exactly one status:
FIRST-RUN READY or NOT FIRST-RUN READY.

Work in priority order. P0 must be done and tested before P1 starts.

---

## P0 — Cannot ship without

### P0.1 No global runtimes (verify, don't assume)
- Search the codebase for any `python`, `py`, `node`, `npm`, `npx`, `cargo`
  invocations or PATH lookups at runtime. Each one is a bug. The only
  processes Prosody may start: the bundled `prosody-core.exe`, the configured
  `FL64.exe`, the bundled `ffmpeg.exe`, and `explorer.exe` (open folder).
- Core packaging: PyInstaller `--onedir --console`, spawned from Rust with
  `creation_flags(0x08000000)` (CREATE_NO_WINDOW). Never `--noconsole` (breaks
  stdio) and never `--onefile` (temp extraction on every launch, slower, more
  antivirus flags). No UPX. Set `PYTHONUTF8=1` in the spawn environment so
  Unicode paths survive. Verify `pyflp`, `mido`, `numpy`, `soundfile` (its
  `libsndfile` DLL), `pydantic_core` and the `genres/` data are collected.
- Architecture guard at build and at startup: read the PE header of
  `prosody-core.exe`, `ffmpeg.exe` and the configured `FL64.exe` (machine
  type must be x64) and refuse to spawn a mismatch with a clear message.
  Fail the build if any bundled binary is not a Windows x64 PE (this is how a
  Linux sidecar sneaks into a Windows release).
- Build-time manifest `resources/build-info.json`: Prosody version, git commit,
  build date, Tauri version, Python version, PyInstaller version, PyFLP
  version, SHA-256 of `prosody-core.exe` and `ffmpeg.exe`. Diagnostics reads
  it; the sidecar re-hashes itself at startup and warns on mismatch.

### P0.2 Startup must never end in a blank window
- Sequence: WebView2 check → portable-mode check → dirs → settings → DB
  integrity → spawn core → ping (10 s) → UI. Every step has a failure screen.
- Core failure: "Prosody Core failed to start" with [Retry] [Diagnostics]
  [Safe Mode]. Show the last 20 lines of `core.log` under Diagnostics only.
- SQLite: enable WAL; run `PRAGMA integrity_check` at startup; on failure
  rename to `prosody.db.corrupt-<timestamp>` and rebuild. Design rule: the DB
  is an index, never the source of truth. Library entries must be
  reconstructable by scanning `Documents\Prosody\Exports\*\data\project.json`,
  so "Rebuild Library" is always safe.
- Safe Mode: `--safe` flag, `safemode.flag` next to the exe, or Shift held at
  launch. Disables FLP writing, FL invocation, AI networking, stem automation.
  Allows inspection, Library, Diagnostics.

### P0.3 Source immutability, enforced in one place
- One module (`core/io/source.py`) is the only code allowed to open a source
  .flp, and it opens read-only. Every writer takes an output path and asserts
  it is inside the Prosody workspace, is not the source path, and does not
  resolve to the same file identity (Windows: compare volume serial + file
  index via `os.stat` `st_dev`/`st_ino`, which Python populates on Windows).
- SHA-256 before and after every operation; mismatch = CRITICAL, abort,
  preserve outputs, log, surface in UI. Never "fix" by rewriting the source.
- Copy-on-analyze: work only from a working copy in
  `%LOCALAPPDATA%\Prosody\Cache\jobs\<job-id>\source.flp`.

### P0.4 Transactional outputs
- Write `<name>.partial`, flush, `os.fsync`, close, validate, hash, then
  `os.replace` to the final name (atomic on the same volume). Cross-volume
  destinations: write the temp file on the destination volume, not in Cache.
- `os.replace` raises `PermissionError` when the destination is open in
  another program (FL, Explorer preview). Catch it and offer the next `V00n`
  name; never delete the locked file.
- Startup scans the workspace for stale `.partial` files and `job.json`
  manifests with incomplete stages; offers Resume / Restart / Discard. Resume
  never touches the source; it re-verifies the source hash first.
- `job.json`: source path + hash, working-copy path, operation, options,
  completed stages with timestamps, outputs with hashes, validation level.

### P0.5 Process control for FL Studio
- One adapter (`core/fl/adapter.py`) owns every FL invocation. Structured
  argument arrays only; dropped filenames are data. Record the exact command
  line in `job.json` for Diagnostics. No `shell=True` anywhere in the repo.
- Assign each spawned FL and ffmpeg process to a Windows Job Object with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (via `pywin32` or ctypes) so a Prosody
  crash cannot leave orphaned renders running. Prosody kills only processes it
  owns; enumerate `FL64.exe` before launching and never touch a pre-existing
  instance.
- Timeout = max(10 min, 60 s × project minutes × 3); on timeout kill the
  owned process, mark the stage FAILED with the log, keep partial files in
  Cache for inspection.
- Detect "user closed FL during render" (exit code without output file) and
  report it as a warning, not a crash. FL's own window appearing during a
  command-line render is expected; say so in the progress UI.
- Disk-space check before any render: estimate
  `bars × 4 × 60 / bpm × sample_rate × channels × bytes_per_sample ×
  (1 + stem_count) × 1.2`, compare with `shutil.disk_usage` on the export
  volume, warn before launching FL.

### P0.6 Tauri permissions (v2 capabilities model)
- Do all process spawning and privileged filesystem work in Rust commands.
  Do not grant `shell:allow-execute` or `shell:allow-open` to the webview at
  all; use `tauri-plugin-opener` (scoped to the workspace) for "Open Output
  Folder" and "Open in FL Studio".
- `fs` scope: workspace, Cache, and user-selected paths only.
- Set a strict CSP in `tauri.conf.json` (no remote script sources).
- Drag-drop: use Tauri v2's drag-drop event; treat the paths as untrusted
  input (validate extension, existence, readability, size ≤ 200 MB).

---

## P1 — Trust and truth

### P1.1 Output validation chain with levels (never collapse to "success")
Levels, in order, each requiring the previous:
- GENERATED — writer produced a file
- STRUCTURALLY_VALIDATED — PyFLP re-parses it; channel, pattern, note,
  plugin, mixer, sample-path counts equal the source; playlist differs as
  planned
- SEMANTICALLY_VALIDATED — an independent parser confirms only allowed
  differences (see P1.2)
- FL_STUDIO_VALIDATED — FL opened it and a command-line render succeeded
  with the expected duration
Show the reached level on the project screen. A derivative that fails any
level is kept as `<name>.unvalidated.flp` in Cache for investigation and is
not placed in Exports.

### P1.2 Independent parser (flpdiff) — how to actually use it
flpdiff is a TypeScript clean-room .flp parser with published format notes.
Confirm its license in its LICENSE file before bundling (permissive is
expected; if it is not, use it in CI only). Because it is JavaScript, do not
bundle Node for it. Options in order of preference:
1. Run it inside the app's own webview: bundle it with Vite, read the source
   and derivative bytes through a Rust command, parse and diff in the webview
   or a Web Worker. Zero new runtime.
2. If it is CLI-only, compile it to a standalone exe with `bun build
   --compile` and ship it as a second sidecar (check size and PE arch).
3. CI/dev-only oracle; release reports SEMANTICALLY_VALIDATED as UNAVAILABLE.
Allowed differences in Preserve Composition: playlist items, playlist track
names, time markers, project title/comments. Forbidden: any change in
pattern note data, channel settings, plugin state blobs, preset data,
sample references, mixer inserts/routing/effects, tempo, time signature,
automation. Any forbidden diff blocks promotion.

### P1.3 MIDI and audio verification (lightweight)
- MIDI: reopen every exported `.mid` with `mido` and compare track count,
  note count, pitch set, tick positions (at project PPQ) and velocities to the
  source pattern. A `.mid` that exists but fails comparison is FAILED. Do not
  add `pretty_midi`; `mido` covers verification.
- Audio: use `soundfile` for duration, peak, RMS and silence checks. Do not
  add `librosa`; nothing here needs it.

### P1.4 System Check (Settings → System Check, also silent on first run)
Rows with PASS / WARNING / UNAVAILABLE / FAIL: Prosody runtime, WebView2
version, core sidecar (version + hash match), FLP parser, FLP validator,
FL Studio (path, version, Test Connection), render engine, MIDI engine,
ffmpeg, database, export directory writable, temp directory writable, disk
space, OS architecture, long-path support.
First-run write test: create and delete a temp file in workspace, Cache and
export dir. [Run System Check] and [Copy Sanitized Report] buttons.
Sanitized report: replace the user profile path with `~`, hash sample paths
unless "include full paths" is ticked, never include API keys or tokens.
Full logs stay local in `%LOCALAPPDATA%\Prosody\Logs\`.

### P1.5 UI truth model
Every capability badge comes from runtime detection, cached per session:
Native FLP generation AVAILABLE / EXPERIMENTAL / UNAVAILABLE; FL validation
AVAILABLE / NOT CONFIGURED; Stems AVAILABLE / EXPERIMENTAL / UNAVAILABLE;
Claude / OpenAI CONFIGURED / NOT CONFIGURED. Nothing hardcoded in the
frontend.

### P1.6 Samples and plugins
- Sample states: AVAILABLE, MISSING, RELOCATED (found by filename + size
  match elsewhere; requires user confirmation), UNKNOWN. Never auto-substitute;
  never rewrite source references.
- Plugins: REFERENCED, DETECTED (registry/VST folder scan), UNKNOWN,
  FAILED_IN_RENDER (from FL's behavior). FL is the authority; Prosody never
  marks a plugin MISSING on its own.

---

## P2 — Distribution quality

### P2.1 WebView2 strategy
- Installer: `bundle.windows.webviewInstallMode = offlineInstaller`
  (~127 MB larger, works with no internet). Document the size trade-off.
- Portable ZIP: WebView2 must already exist. At startup check
  `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`
  (and the HKCU equivalent); if absent show a native message box with the
  Evergreen runtime download link and exit. Optionally produce a second
  `Prosody-portable-full` ZIP using `fixedRuntime` for true offline portable
  use; it is larger but has no external dependency.
- Test with WebView2 absent: Windows Sandbox is the cheapest way (see P2.5).

### P2.2 Mark-of-the-Web and SmartScreen
- A ZIP downloaded by a browser carries a `Zone.Identifier` stream; Explorer
  propagates it to every extracted file, so `Prosody.exe` and the sidecar get
  SmartScreen prompts on first run. Expected for an unsigned build. README.txt
  must explain "More info → Run anyway" and the alternative of right-click →
  Properties → Unblock on the ZIP before extracting.
- Test the real path: download the release ZIP in Edge on the test account,
  extract with Explorer, launch. Record every prompt.
- Defender false positives on PyInstaller binaries happen; if one appears,
  note the detection name and submit the file to Microsoft's false-positive
  portal. Do not ship UPX-packed binaries.

### P2.3 Code-signing readiness (not signing yet)
- `tauri.conf.json` `bundle.windows`: leave `certificateThumbprint` null,
  set `digestAlgorithm: "sha256"` and `timestampUrl` to a public RFC 3161
  server; support `signCommand` so a cloud signer can be plugged in.
- Document the path: since 2023 OV certificates must live on hardware or a
  cloud HSM; the practical route for a small LLC is Azure Trusted Signing
  (subscription-priced, no token) driven through `signCommand`, or an EV cert
  on a token. SmartScreen reputation still builds over time after signing.
- Tauri's updater uses its own minisign keypair, separate from Authenticode.
  Do not generate or commit either key in this pass; document where they go.

### P2.4 Windows filesystem edge cases (tests, not hopes)
- Enable `longPathAware` in the Windows app manifest and prefix paths with
  `\\?\` in the core when they exceed 240 chars.
- Test fixtures with spaces, Unicode, emoji, apostrophes, parentheses,
  `# & % !`, 250-char paths, deep nesting, read-only source folders, a
  source on a USB drive, samples on a different drive than the project.
- OneDrive: detect cloud-only placeholders
  (`FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`) and warn that the file will be
  downloaded first; do not hang silently.
- Locked destination, source currently open in FL, full-disk simulation
  (a small VHD or a quota): each must fail safely with a message.

### P2.5 Clean-Windows testing setup (ship the harness)
- `test/sandbox/prosody.wsb`: Windows Sandbox config mapping the release
  folder read-only and launching `Prosody.exe` on logon. Sandbox has no FL,
  no Python, no Node, no WebView2 guarantee: perfect for first-run, offline
  and FL-absent tests. Windows 10/11 Pro feature; enable via Windows Features.
- FL-present tests run on the studio PC under a second local Windows account
  with no dev tools on PATH.
- Evidence: screenshots or logs per test, stored under `docs/evidence/<date>/`.

### P2.6 Licensing inventory (documentation, not legal advice)
- `THIRD_PARTY.md` + `licenses/`: name, version, homepage, license, bundled
  yes/no, purpose, for every runtime component: PyFLP (GPL-3.0), Tauri (MIT/
  Apache-2.0), mido (MIT), numpy (BSD), soundfile + libsndfile (BSD / LGPL),
  pydantic (MIT), ffmpeg (GPL or LGPL depending on the build you bundle;
  record which), PyInstaller (GPL with bootloader exception), flpdiff (verify),
  fonts.
- Architectural boundary: PyFLP lives only inside the sidecar process and is
  reached over stdio; keep parse/write behind the existing Backend protocol
  so a permissive parser can replace it for read-only inspection later. Note
  in THIRD_PARTY.md that process separation is a design boundary, not a
  settled legal one, and that distribution beyond private use needs a proper
  license review.
- Generate a CycloneDX SBOM if the toolchain makes it cheap (`cyclonedx-py`,
  `cargo cyclonedx`, `@cyclonedx/cyclonedx-npm`); otherwise THIRD_PARTY.md is
  the minimum.

### P2.7 Reproducible builds
- Commit `uv.lock` (or `requirements.txt` from `pip-compile`),
  `package-lock.json`, `Cargo.lock`. Pin PyInstaller and the Tauri CLI.
- CI release workflow uses `npm ci`, `uv sync --frozen` (or `pip install -r`
  with hashes), and fails on lockfile drift. Release notes list versions
  from `build-info.json`.
- `docs/FL_COMPATIBILITY.md`: FL version × parse / write / open generated /
  render / MIDI export / ZIP export / stems, one row per version actually
  tested, with date. Never claim untested versions.

---

## Acceptance gate — FIRST-RUN READY means all of these passed on the release artifact, not the dev tree

1. Starts from a folder outside the repo, in a second Windows account, with
   no dev tools on PATH
2. No dev server, no global Python, no global Node, no Git, no GitHub needed
3. WebView2 handled (installer offline; portable detects and explains)
4. Core sidecar starts; hash matches build-info
5. Workspace and DB initialize; System Check completes with no FAIL
6. Source read-only safeguards pass their tests
7. FL detection correct with FL present and with FL absent (Sandbox)
8. One real .flp analyzes; one arrangement plan generates (Rules Only, offline)
9. Derivative reaches at least STRUCTURALLY_VALIDATED, or the Arrangement
   Pack fallback is shown with its message
10. Source hash unchanged after every operation
11. Outputs and Library survive restart
12. Offline first run works (network adapter disabled)
13. Logs and the sanitized report contain no secrets
14. Downloaded-ZIP path tested with Mark-of-the-Web intact; prompts documented

## Final response (nothing else)

FIRST RUN — exact steps from downloaded artifact to open Prosody
BUNDLED — everything in the release, with sizes
EXTERNAL REQUIREMENTS — ideally only FL Studio for FL-dependent features
VALIDATED — capabilities actually tested, with evidence paths
EXPERIMENTAL — capabilities with limited evidence
DEPENDENCIES — name, version, license, purpose
COMPATIBILITY — exact Windows and FL Studio versions tested
FAILURE RECOVERY — what happens if first run fails
RELEASE ARTIFACTS — exact paths and SHA-256
STATUS — FIRST-RUN READY or NOT FIRST-RUN READY

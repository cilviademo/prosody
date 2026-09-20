# RELEASE.md — Prosody v0.1: standalone Windows release

Objective for this session: produce a portable ZIP that a user extracts and
double-clicks `Prosody.exe`, with no Python, Node, Rust, Git, GitHub, terminal
or dev server on their machine. An NSIS installer is a second deliverable.
Rebrand everything from Asterism to Prosody as part of this work.

Do not write plans or reports first. Read the repo, then execute the steps in
order. Stop only for a genuine blocker, and record it in CURRENT_STATUS.md.

---

## 0. Where this runs (read before anything else)

Windows binaries must be built on Windows. Decide once, at the start:

- **If this session is on the studio PC (Windows):** build locally with
  `scripts/build-release.ps1` (step 8) and also add the GitHub Actions workflow
  (step 9) so releases don't depend on the dev machine.
- **If this session is on Linux/macOS/a container:** do all code and config
  work here, commit, then add the GitHub Actions workflow (step 9) and push a
  tag. The workflow's `windows-latest` job produces the ZIP and installer as
  release assets. Do not attempt to cross-compile a Windows Tauri bundle from
  Linux; it will not produce a usable NSIS installer.

Either way the end user downloads a ZIP from the GitHub Releases page in a
browser. No `gh`, no clone, no login for a public repo (a private repo needs a
browser login only).

## 1. Rebrand Asterism → Prosody

- Repo-wide rename (code, config, UI strings, docs, workspace paths). Grep for
  `asterism`/`Asterism`/`ASTERISM` until zero hits outside git history.
- `tauri.conf.json`: `productName: "Prosody"`, `identifier: "com.multibanded.prosody"`,
  `version: "0.1.0"`, window title `Prosody`, default size 1040×720, min 860×600.
- Icon: generate an original 1024×1024 PNG (simple geometric mark, dark
  background, no text) and run `tauri icon` to produce the full icon set.
- Output naming: `SOURCE__PROSODY_<GENRE>_V001.flp`, incrementing V002…
- Workspace: `%USERPROFILE%\Documents\Prosody\{Exports,Projects}`;
  app state: `%LOCALAPPDATA%\Prosody\{prosody.db,settings.json,Cache,Logs}`.

## 2. Self-contained backend (the hard part; do it before packaging)

The Python core stays; ship it as a bundled binary, not as "install Python".

- Build the core with **PyInstaller in `--onedir` mode** (not onefile: onefile
  extracts to temp on every launch, adds 2–5 s startup and trips antivirus).
  Entry point `prosody_core/__main__.py`, output `prosody-core/` containing
  `prosody-core.exe` + `_internal/`.
- Build it as a **console** executable (`--console`), so stdin/stdout work,
  and have Tauri spawn it with `CREATE_NO_WINDOW` (`creation_flags(0x08000000)`)
  so no console window ever appears. Do not use `--noconsole`; it breaks stdio.
- Hidden imports and data to verify in the spec file: `pyflp`, `mido`, `numpy`,
  `soundfile` (collect its `libsndfile` DLL), `pydantic` (v2 core), the
  `genres/*.json` folder, and anything loaded by path.
- Ship the whole `prosody-core/` folder as a Tauri **resource**
  (`bundle.resources`), and spawn `prosody-core.exe` from
  `app.path().resource_dir()` via `std::process::Command`. Do not use the
  `externalBin` sidecar mechanism for an onedir bundle; it expects one file.
- **IPC: JSON lines over stdio.** One request per line, one response or
  progress event per line, request ids for correlation. No localhost HTTP
  server in the release build (avoids port collisions and firewall prompts).
  If the backend is already FastAPI, wrap the same handlers in a stdio loop;
  keep HTTP only behind a `--http` flag for development.
- ffmpeg for MP3: bundle a static `ffmpeg.exe` under `resources/bin/` with its
  license text in `licenses/`. Never call ffmpeg from PATH.
- Startup contract: Tauri spawns the core, sends `{"id":1,"method":"ping"}`,
  expects `{"id":1,"ok":true,"version":"0.1.0"}` within 10 s. On failure show a
  Diagnostics screen with the log path, not a blank window and not a crash.
- Core logs go to `%LOCALAPPDATA%\Prosody\Logs\core.log` (rotating, 5 × 5 MB);
  UI/Rust logs to `app.log` in the same folder.

## 3. Startup sequence (Rust side, in this order)

1. WebView2 check. Tauri needs the Edge WebView2 runtime; it is present on
   Windows 11 and most Windows 10. In `tauri.conf.json` set
   `bundle.windows.webviewInstallMode` to `embedBootstrapper` for the installer.
   For the portable ZIP, if WebView2 is missing, show a native message box with
   the Microsoft download link and exit cleanly.
2. Portable-mode check: if `portable.flag` exists next to `Prosody.exe`, use
   `<exe dir>\Data\` for db, settings, cache, logs instead of `%LOCALAPPDATA%`.
3. Create directories, load `settings.json` (create defaults on first run).
4. Detect FL Studio (step 4). Store the result; never re-prompt if a saved
   path still exists on disk.
5. Open/migrate `prosody.db`.
6. Spawn the core and ping.
7. Show the Finish screen. First run only: the "FL Studio detected / not
   detected" interstitial with `Continue` or `Locate FL Studio` /
   `Continue without rendering`.

Restore window position and size from settings; clamp to the current monitor.

## 4. FL Studio discovery and invocation

- Search, in order: `HKLM\SOFTWARE\Image-Line\*` and
  `HKCU\SOFTWARE\Image-Line\*` install paths; then
  `C:\Program Files\Image-Line\FL Studio 2025\FL64.exe`, `… 2024`, `… 21`,
  `… 20`; then the same under `Program Files (x86)`. Present the newest found.
- Settings: `FL64.exe path` · `Change` (file picker) · `Test Connection`
  (launches `FL64.exe` with the render switch on a tiny bundled test .flp,
  10-min timeout, reports pass/fail and duration).
- Spawn FL with `CREATE_NO_WINDOW` for the *shell*, but tell the user in the
  progress UI: "FL Studio will open briefly while rendering." FL's own window
  during a command-line render is expected and cannot be hidden.
- Capture exit code and any log FL writes; surface failures as a warning on
  the stage, never as a raw terminal dump.
- No FL configured → analysis, classification, arrangement planning, MIDI,
  ZIP and Arrangement Pack still work; WAV/MP3/stems show "Requires FL Studio".

## 5. Offline and safety guarantees (enforce in code, cover in tests)

- Zero network calls unless an AI provider is enabled in Settings. Default is
  Rules Only. Run the release once with the network disabled as a test.
- Source .flp hash computed on drop; re-verified before and after every
  operation; any mismatch aborts and logs. Sources are opened read-only.
- Never write into the source folder unless the user picked it as the export
  location.
- No secrets in the bundle. API keys, if entered, live in `settings.json`
  under `%LOCALAPPDATA%` (or `Data/` in portable mode), never in resources.

## 6. Release contents

Portable ZIP `Prosody-v0.1.0-Windows.zip` extracts to:

```
Prosody/
  Prosody.exe
  resources/
    prosody-core/ (exe + _internal/)
    bin/ffmpeg.exe
    genres/*.json
  licenses/        (Tauri, PyFLP, ffmpeg, fonts, etc.)
  README.txt       (how to run, SmartScreen note, where files go, portable.flag)
```

Exclude: source, `node_modules`, tests, fixtures, personal .flp files, `.git`,
`.claude`, dev docs, `.env`.

Installer `Prosody-v0.1.0-Setup.exe` (NSIS, per-user install, no admin,
Start Menu shortcut, optional desktop shortcut, standard uninstall).

Both are unsigned. README.txt and RELEASE_NOTES.md must say: Windows
SmartScreen will show "Windows protected your PC" on first launch; click
"More info" → "Run anyway". Do not self-sign; it adds nothing.

`release/` contains the ZIP, the installer, `SHA256SUMS.txt`, `RELEASE_NOTES.md`.

## 7. Portable ZIP is not a Tauri target — script it

`tauri build` produces the installer and a bare `Prosody.exe` in
`src-tauri/target/release/`; resources are resolved next to the exe on
Windows. `scripts/make-portable.ps1` must:

1. Copy `Prosody.exe`, the `resources/` tree exactly as the bundle lays it
   out, and `licenses/` into `dist/Prosody/`.
2. Write `README.txt`.
3. Zip to `release/Prosody-v<version>-Windows.zip`.
4. Append SHA-256 of every release file to `release/SHA256SUMS.txt`.

Verify the layout by running the extracted copy, not by reading the script.

## 8. Local build (Windows only)

`scripts/build-release.ps1`, run from a plain PowerShell:

1. `python -m PyInstaller prosody-core.spec` → `build/prosody-core/`
2. Copy into `src-tauri/resources/prosody-core/`
3. `npm ci && npm run tauri build`
4. `scripts/make-portable.ps1`
5. Print the exact paths of `Prosody.exe`, the ZIP and the installer.

## 9. GitHub Actions release workflow (always add this)

`.github/workflows/release.yml`, triggered on tags `v*`:

- `runs-on: windows-latest`
- setup Python 3.12 → `pip install -r requirements.txt pyinstaller` → build core
- setup Node 20 → `npm ci`
- setup Rust stable (msvc) → `npm run tauri build`
- run `scripts/make-portable.ps1`
- upload `release/*` as workflow artifacts **and** attach them to a GitHub
  Release for the tag (`softprops/action-gh-release` or equivalent).

Pin action versions. The workflow must succeed from a clean checkout with no
secrets; if it needs one, that's a bug.

## 10. Clean-machine acceptance test (the real definition of done)

Run this on the studio PC in a **new local Windows user account** that has no
Python, Node, Rust or Git on PATH (that is the closest thing to a fresh
machine without a VM). If a second account is impossible, run from a
PowerShell where PATH is reduced to `C:\Windows\System32` only.

1. Copy only `Prosody-v0.1.0-Windows.zip` to `C:\Temp\prosody-test\`.
2. Close every dev server, terminal and editor.
3. Extract and double-click `Prosody.exe`. It opens as a native window with
   the Prosody icon and title; no console, no browser.
4. FL Studio detection result matches reality; `Test Connection` passes.
5. Drop a real 4-bar .flp. BPM, patterns, channels, plugins match FL.
6. Choose R&B → Preserve Composition → see the timeline → Build.
7. Outputs land in `Documents\Prosody\Exports\<name>__PROSODY_RNB_V001\`
   with at least Full.wav, Full.mp3, MIDI, arrangement.json, and either the
   derivative .flp or an Arrangement Pack with the stated fallback message.
8. Source .flp hash unchanged (compare `Get-FileHash` before and after).
9. `Open Output Folder` and, if a .flp exists, `Open in FL Studio` both work.
10. Close Prosody. Relaunch. Settings, FL path and Library persist.
11. Repeat 3–5 with `portable.flag` next to the exe; confirm `Data\` is used
    and `%LOCALAPPDATA%\Prosody` is not written.
12. Disable the network adapter; repeat 5–7 with Rules Only.
13. Run the installer; confirm Start Menu entry, launch, and clean uninstall
    (no leftover files except the user's Documents\Prosody exports).

Record each step's result in `CURRENT_STATUS.md` (WORKING / PARTIAL /
NOT YET WORKING / KNOWN ISSUES / NEXT PRIORITY). No step may be marked
WORKING unless it was actually executed.

## 11. Final response to me (nothing else)

1. Exact path to `Prosody.exe` (and the GitHub Release URL if built by CI).
2. Exact path to the portable ZIP.
3. Exact path to the installer, or the reason it wasn't produced.
4. Did the clean-account test pass? Which steps failed?
5. Was FL Studio detected, and did Test Connection pass?
6. Verified functions.
7. Experimental or falling-back functions.
8. The single highest-priority remaining limitation.

# Prosody v0.1.0

Turn loops into records.

Drop an unfinished FL Studio project, choose a genre, and get an arranged
derivative `.flp` — plus per-role MIDI and a portable package — without ever
modifying your original.

## Getting it running

**One line.** Open PowerShell — the one already on your PC, no admin — and
paste:

```powershell
irm https://raw.githubusercontent.com/cilviademo/prosody/main/scripts/install.ps1 | iex
```

It downloads this release, checks its SHA-256 against `SHA256SUMS.txt` below,
installs it, clears the download marker so SmartScreen stays quiet, adds a
Start Menu entry and starts the app. Re-run it later to update.

**Portable:** extract `Prosody-v0.1.0-Windows.zip` anywhere you can write to
and double-click `Prosody.exe`. Keep the folder together.

**Installed:** run `Prosody-v0.1.0-Setup.exe`. Per-user, no administrator
rights, standard uninstall.

Nothing else is required. Python, Node and Rust are not needed — Prosody ships
its own core.

### First launch

Windows SmartScreen will show **"Windows protected your PC"** because these
builds are not code-signed. Click **More info** → **Run anyway**. Once only.
Signing needs a paid certificate; self-signing would change nothing.

If Windows reports that the **Edge WebView2 runtime** is missing (some Windows
10 machines), install it from
<https://go.microsoft.com/fwlink/p/?LinkId=2124703>. The installer includes it;
the portable build cannot install it and will tell you instead of opening a
blank window.

## What works without FL Studio

Analysis, role classification, arrangement planning, the arranged `.flp`,
per-role MIDI and the portable project. WAV, MP3 and stems need FL Studio —
point Prosody at `FL64.exe` under **Settings**, then use **Test Connection**,
which renders a one-bar project and reports what actually happened.

While rendering, **FL Studio opens its own window**. That is expected during a
command-line render and cannot be suppressed.

## Your originals

Prosody hashes every source `.flp` before it starts and checks it again
afterwards; a mismatch aborts the build. Output goes to a new versioned folder
under `Documents\Prosody\Exports\` and nothing is ever overwritten.

At the default creativity level — **Preserve Composition** — Prosody may
repeat, reposition and mute the patterns you already have. It may not edit
notes, generate melodies, change chords or touch your plugins and mixer. That
is enforced in code at two independent gates, not by instructions to a model.

## Offline

No network calls. AI planners are optional, off by default, and would only ever
receive numbers and role names.

## Portable mode

Create an empty file named `portable.flag` next to `Prosody.exe`. Prosody then
keeps everything in a `Data` folder beside the executable and writes nothing to
your user profile.

## Known limitations

- **Audio rendering and stems have never been run against a real FL Studio
  install.** The command-line wrapper is written and gated behind detection,
  but the first person to try it is finding out with it.
- **No real FL Studio project has been parsed yet** — every fixture is
  synthetic. Parse rate against real projects is unmeasured.
- **Creativity levels 1 and 2 are not implemented.** They are selectable and
  the app says so; the engine only ever repositions existing patterns.
- **PyFLP is GPL-3.0** and is bundled inside the core. That carries obligations
  for public distribution which have not been resolved — fine for private use.
- The builds are unsigned.

Full detail in `CURRENT_STATUS.md`.

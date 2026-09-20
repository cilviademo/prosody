# Asterism

**Turn loops into records.**

A local, Windows-first desktop application that turns an unfinished FL Studio
loop into a fully arranged derivative project — plus MIDI, audio and a portable
package — without ever modifying your original `.flp`.

Drop a project → pick a genre → Finish.

---

## What it does

1. **Drop an `.flp`.** Asterism reads its tempo, key, patterns, channels,
   plugins, mixer and samples, and classifies each channel's musical role.
2. **Choose Extract, Arrange, or both.**
3. **Pick a genre and structure.** Hip-hop, R&B, pop, trap, EDM or drum & bass;
   short, balanced or full-length.
4. **See the arrangement before it is built** — section blocks and a lane per
   role.
5. **Build.** You get an arranged `.flp` you can open in FL Studio, per-role
   MIDI, a portable ZIP, and — with FL Studio configured — WAV, MP3 and stems.

Your original file is hashed before the build and re-verified afterwards. It is
never written to, moved or renamed.

### Preserve Composition

The default creativity level, and the reason the product exists. Asterism may
repeat, reposition, mute and structure the patterns you already have. It may
**not** edit notes, generate melodies, change chords, replace sounds, or touch
your plugin presets or mixer.

This is enforced in code at two independent gates, not by instructions to a
model: an arrangement plan containing a note-editing operation cannot be
constructed at Level 0, and the writer re-checks every operation immediately
before it writes a byte.

---

## Install

**Requirements:** Windows 10/11, and Python 3.10 or newer on `PATH`.
FL Studio is optional — it is only needed for audio and stems.

### Run from source

One command, from the repository root:

```powershell
.\scripts\setup-windows.ps1
```

It creates the virtualenv, installs the backend and the desktop dependencies,
runs `flpf doctor`, and launches Asterism. Needs Python 3.10+, Node 18+ and
Rust (from rustup.rs) on `PATH`.

By hand, if you prefer:

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
cd apps\desktop
npm install
npm run app          # launches Asterism (tauri dev)
```

On Linux or macOS, `./scripts/setup.sh` does the same. FL Studio is
Windows-only, so rendering and stems stay unavailable there.

### Build a Windows installer

Run this **on the Windows machine** — Tauri cannot cross-compile a Windows
bundle from Linux or macOS.

```powershell
.\scripts\setup-windows.ps1 -Bundle
```

or, by hand:

```powershell
cd apps\desktop
npm run bundle
```

The installer lands in:

```
apps\desktop\src-tauri\target\release\bundle\nsis\Asterism_0.1.0_x64-setup.exe
apps\desktop\src-tauri\target\release\bundle\msi\Asterism_0.1.0_x64_en-US.msi
```

If Asterism cannot find Python it says so on startup. Set `ASTERISM_PYTHON` to
an interpreter path to override the search.

---

## Configure FL Studio

Open **Settings**. Asterism looks for FL Studio in the registry
(`HKLM\SOFTWARE\Image-Line\Shared\Paths`), then the usual install folders, then
`PATH` — no single path is hardcoded. If it is not found, use **Change** to
pick `FL64.exe`, then **Test Connection**.

Turn **Rendering** on to let Asterism run FL Studio for WAV, MP3 and stems.
Everything else — analysis, arrangement, the derivative `.flp`, MIDI, ZIP —
works without FL Studio at all.

---

## Where your files go

Asterism writes only inside its own workspace, never beside your sources:

```
Documents/Asterism/
  Projects/  Cache/  Logs/  Database/
  Exports/
    Starfall__ASTERISM__RNB_V001/
      Starfall__ASTERISM__RNB.flp     the arranged project
      Starfall__ASTERISM__RNB.zip     portable package
      preview/   Full.wav  Full.mp3
      stems/     Kick.wav  Snare.wav  …
      midi/      01_Chords.mid  02_Melody.mid  …
      data/      project.json  analysis.json  arrangement.json
      reports/   health.json  validation.json  operations.log
```

Output folders are versioned (`_V001`, `_V002`, …) and never overwritten.
Change the location under **Settings → Export folder**.

---

## If something is missing

Asterism degrades instead of failing. Each build step reports its own outcome:

- **No FL Studio?** WAV, MP3 and stems are disabled with the reason shown. The
  arranged `.flp`, MIDI and ZIP are still produced.
- **Missing samples?** The project still arranges — the derivative keeps the
  same references — and the missing paths are listed in the report and the ZIP.
- **A project the writer cannot safely rewrite?** You get an **Arrangement
  Pack** instead: the plan, per-role MIDI and any audio that rendered. That is
  a supported result, not an error.

Nothing is ever faked. Stems are never copies of the master render, and an
unavailable feature is switched off with an explanation rather than producing
something that looks right and is not.

---

## Privacy

Everything is local. There is no network code in the backend — verified by a
test that walks every module's imports. AI planners are optional, off by
default, and would only ever receive sanitised numbers and role names: never
your audio, projects, file paths or project names. See
[docs/privacy.md](docs/privacy.md).

---

## Command line

The GUI orchestrates everything; the CLI remains for diagnostics.

```bash
flpf doctor                     # what this machine can and cannot do
flpf inspect path/to/beat.flp   # summarise one project
flpf scan folder/               # parse a folder, report the parse rate
```

---

## Status

See **[CURRENT_STATUS.md](CURRENT_STATUS.md)** for exactly what works, what is
partial, and what is not built yet.

The short version: the full drop → analyse → arrange → export loop works and
produces a valid derivative `.flp`. Audio rendering and stems are written but
have **never been run against a real FL Studio install** — that is the next
thing to verify, on the studio PC.

## Known limitations

[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) has the full list. The ones that
matter most:

- No real FL Studio project has been parsed yet; every fixture is synthetic.
- Audio rendering and stem extraction are unexercised against FL Studio.
- PyFLP 2.2.1 cannot parse anything on Python 3.11+ without the compatibility
  shim this project ships ([ADR-0002](docs/adr/ADR-0002-pyflp-enum-compat.md)).
- Creativity levels 1 and 2 are not implemented; the engine only repositions
  existing patterns.

---

## Documentation

| File | What it is |
| --- | --- |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | Working / partial / not working / issues / next |
| [ARCHITECTURE.md](ARCHITECTURE.md) | How it is put together and why |
| [SPEC.md](SPEC.md) | The original contract |
| [DECISIONS.md](DECISIONS.md) | Decision log and ADR index |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | What does not work |
| [docs/privacy.md](docs/privacy.md) | What leaves your computer (nothing) |
| [docs/testing.md](docs/testing.md) | Test tiers and how to run them |
| [docs/flp-compatibility.md](docs/flp-compatibility.md) | FLP format notes, verified and not |

## Tests

```bash
pytest                              # 466 unit tests; corpus and render auto-skip
pytest -m corpus                    # needs real .flp files in corpus/
FLPF_RENDER=1 pytest -m render      # studio PC only
```

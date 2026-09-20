# Third-party components

Prosody ships the following components inside its release. Each is used
unmodified unless noted.

| Component | Version | Licence | Bundled | Purpose | Source |
| --- | --- | --- | --- | --- | --- |
| PyFLP | 2.2.1 | GPL-3.0-or-later | yes | reads `.flp` projects | https://github.com/demberto/PyFLP |
| construct | via PyFLP | MIT | yes | binary structs PyFLP builds on | https://github.com/construct/construct |
| pydantic | 2.13.5 | MIT | yes | the data contract in `model/schemas.py` | https://github.com/pydantic/pydantic |
| pydantic-core | via pydantic | MIT | yes | compiled validator core | https://github.com/pydantic/pydantic-core |
| mido | 1.3.3 | MIT | yes | MIDI export and verification | https://github.com/mido/mido |
| typer | 0.27.2 | MIT | yes | the `flpf` CLI | https://github.com/fastapi/typer |
| rich | 15.0.0 | MIT | yes | CLI output | https://github.com/Textualize/rich |
| CPython runtime | 3.12 | PSF-2.0 | yes | runs the core | https://github.com/python/cpython |
| PyInstaller | 6.22.3 | GPL-2.0 with bootloader exception | bootloader only | freezes the core | https://github.com/pyinstaller/pyinstaller |
| Tauri | 2.x | MIT or Apache-2.0 | yes | the window and IPC | https://github.com/tauri-apps/tauri |
| tauri-plugin-opener | 2.5.5 | MIT or Apache-2.0 | yes | opens folders and files | https://github.com/tauri-apps/plugins-workspace |
| tauri-plugin-dialog | 2.7.3 | MIT or Apache-2.0 | yes | the file picker | https://github.com/tauri-apps/plugins-workspace |
| winreg (stdlib) | 3.12 | PSF-2.0 | yes | FL Studio discovery | part of CPython |
| React | 18.3 | MIT | yes | the interface | https://github.com/facebook/react |
| Edge WebView2 runtime | evergreen | Microsoft distributable licence | installer only | renders the interface | https://developer.microsoft.com/microsoft-edge/webview2/ |

The exact versions in any given build are recorded in
`resources/prosody-core/build-info.json` and shown in Settings, so a report can
name the build it came from rather than a version this table happened to say.

## The PyInstaller bootloader

PyInstaller is GPL-2.0, but its bootloader carries an explicit exception
permitting distribution of frozen applications under any licence. Only the
bootloader is in the shipped binary; PyInstaller itself is a build-time tool
and is not distributed.

## PyFLP and the GPL

PyFLP is GPL-3.0-or-later and is bundled inside the Prosody core executable.
Distributing that binary carries GPL obligations for the combined work. This
has **not** been resolved for public distribution — see KNOWN_LIMITATIONS.md.
It is not an issue for private or internal builds.

Prosody applies a four-line compatibility shim to PyFLP at runtime; it is in
`prosody_core/parse/_pyflp_compat.py` and is described in
`docs/adr/ADR-0002-pyflp-enum-compat.md`.

**Process separation is a design boundary, not a settled legal position.**
PyFLP is reached only inside the core process, over stdio, behind the backend
protocol in `prosody_core/parse/adapter.py`. That boundary exists so a
permissively licensed parser could replace it for read-only inspection later.
It is deliberately *not* offered here as an argument that the GPL does not
reach the combined work — that question needs a proper licence review before
Prosody is distributed beyond private use, and this file is documentation
rather than legal advice.

## Not bundled, and why not

| Component | Why it is absent |
| --- | --- |
| ffmpeg | Nothing calls it. FL Studio encodes MP3 itself during a command-line render, so bundling it would add tens of megabytes and a GPL/LGPL question for no capability. System Check reports it as "not present — not required". |
| numpy, soundfile | Declared as the optional `preview` extra for a stitcher that has not been built. `prosody-core.spec` excludes them explicitly and says how to add them back. |
| flpdiff | The independent parser HARDENING P1.2 suggests for semantic validation. Not bundled: its licence has not been verified from its own LICENSE file, and adding a JavaScript parser needs either the webview or a second sidecar. `SEMANTICALLY_VALIDATED` is therefore unreachable, and `validation.json` says so in `level_detail` rather than inflating the level. |
| Node.js | A build-time tool only. The release contains no JavaScript runtime beyond the WebView2 the user's Windows already provides. |

If a future feature does need ffmpeg it belongs at
`resources/bin/ffmpeg.exe` with its LGPL or GPL notice added to the table above
— record which build was used, because the licence differs — and
`prosody_core.env.find_ffmpeg` already looks for it there.

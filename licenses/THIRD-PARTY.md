# Third-party components

Prosody ships the following components inside its release. Each is used
unmodified unless noted.

| Component | Version | Licence | Source |
| --- | --- | --- | --- |
| PyFLP | 2.2.1 | GPL-3.0-or-later | https://github.com/demberto/PyFLP |
| pydantic | 2.13.5 | MIT | https://github.com/pydantic/pydantic |
| mido | 1.3.3 | MIT | https://github.com/mido/mido |
| typer | 0.27.2 | MIT | https://github.com/fastapi/typer |
| rich | 15.0.0 | MIT | https://github.com/Textualize/rich |
| CPython runtime | 3.12 | PSF-2.0 | https://github.com/python/cpython |
| Tauri | 2.x | MIT or Apache-2.0 | https://github.com/tauri-apps/tauri |
| React | 18.3 | MIT | https://github.com/facebook/react |

## PyFLP and the GPL

PyFLP is GPL-3.0-or-later and is bundled inside the Prosody core executable.
Distributing that binary carries GPL obligations for the combined work. This
has **not** been resolved for public distribution — see KNOWN_LIMITATIONS.md.
It is not an issue for private or internal builds.

Prosody applies a four-line compatibility shim to PyFLP at runtime; it is in
`prosody_core/parse/_pyflp_compat.py` and is described in
`docs/adr/ADR-0002-pyflp-enum-compat.md`.

## Not bundled

ffmpeg is **not** included. Nothing in Prosody calls it today: FL Studio
renders MP3 natively through its own command line. If a future feature needs
ffmpeg, it belongs in `resources/bin/ffmpeg.exe` with its LGPL/GPL notice
added here, and `prosody_core.env.find_ffmpeg` already looks for it there.

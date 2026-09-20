"""Write resources/build-info.json for a packaged build.

Run after PyInstaller and before the Tauri bundle, from the repository root:

    python scripts/build_info.py dist/prosody-core

It records what produced this build so Diagnostics and a bug report can name
it exactly, and the SHA-256 of the core so the core can re-verify itself at
startup (HARDENING P0.1).
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _version(module: str) -> str:
    try:
        from importlib.metadata import version

        return version(module)
    except Exception:  # noqa: BLE001 - a missing version must not fail a build
        return "unknown"


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _tauri_version() -> str:
    conf = ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
    try:
        return json.loads(conf.read_text(encoding="utf-8")).get("version", "unknown")
    except (OSError, ValueError):
        return "unknown"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    bundle = Path(argv[1]).resolve()
    if not bundle.is_dir():
        print(f"not a directory: {bundle}", file=sys.stderr)
        return 1

    core = next(
        (bundle / name for name in ("prosody-core.exe", "prosody-core") if (bundle / name).is_file()),
        None,
    )
    if core is None:
        print(f"no core executable in {bundle}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(ROOT))
    from prosody_core.buildinfo import sha256

    info = {
        "build": "release",
        "prosodyVersion": _tauri_version(),
        "gitCommit": _git_commit(),
        "builtAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builtOn": f"{platform.system()} {platform.release()}",
        "pythonVersion": platform.python_version(),
        "pyinstallerVersion": _version("pyinstaller"),
        "pyflpVersion": _version("pyflp"),
        "midoVersion": _version("mido"),
        "pydanticVersion": _version("pydantic"),
        "coreSha256": sha256(core),
    }

    target = bundle / "build-info.json"
    target.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")
    for key, value in info.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

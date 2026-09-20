"""Portable project packaging: the .flp plus every sample it can find."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from prosody_core.model.schemas import BeatProject


@dataclass
class PackageReport:
    path: Path
    files: int = 0
    samples_included: int = 0
    samples_missing: tuple[str, ...] = ()


def package_project(
    flp: Path, project: BeatProject, destination: Path,
    *, extra: dict[str, Path] | None = None,
) -> PackageReport:
    """Zip the project with its resolvable samples under ``Samples/``.

    Third-party plugin binaries are never copied - only project data and audio
    the user already owns.
    """
    flp = Path(flp)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    included = 0
    missing: list[str] = []
    count = 0

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(flp, flp.name)
        count += 1

        seen: set[str] = set()
        for sample in project.samples:
            source = Path(sample.path)
            if not source.is_file():
                missing.append(sample.path)
                continue
            name = source.name
            suffix = 1
            while name in seen:
                name = f"{source.stem}_{suffix}{source.suffix}"
                suffix += 1
            seen.add(name)
            archive.write(source, f"Samples/{name}")
            included += 1
            count += 1

        for arcname, path in (extra or {}).items():
            if Path(path).is_file():
                archive.write(path, arcname)
                count += 1

        if missing:
            archive.writestr(
                "MISSING_SAMPLES.txt",
                "These samples could not be found when the package was built:\n\n"
                + "\n".join(missing) + "\n",
            )
            count += 1

    return PackageReport(
        path=destination, files=count, samples_included=included,
        samples_missing=tuple(missing),
    )

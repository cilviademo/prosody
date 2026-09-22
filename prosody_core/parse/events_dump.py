"""An inventory of every event in a project, for diagnosis by paste.

When a project cannot be read, the thing that resolves it is not the
exception — it is knowing which event ids the file contains, how many of
each, how big, and what the text ones say. That is a table a user can paste
into a bug report without sharing the project itself: no note data, no
plugin state, no sample paths, only ids, counts, sizes and short name previews.

``flpf events <file>`` prints it; ``project.events`` returns it to the app.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prosody_core.parse import native_backend as nb
from prosody_core.write.eventstream import read_flp

#: Text-bearing ids whose first value is worth previewing. Sample paths (196)
#: and plugin data are deliberately not previewed: they can identify a person.
PREVIEW_IDS = frozenset({
    nb.TITLE, nb.CHANNEL_NAME, nb.PATTERN_NAME, nb.INSERT_NAME, nb.MARKER_NAME,
    nb.DISPLAY_GROUP_NAME, nb.TRACK_NAME, nb.ARRANGEMENT_NAME, nb.PLUGIN_NAME,
    nb.PLUGIN_INTERNAL_NAME, nb.FL_VERSION,
})


def pyflp_names() -> dict[int, str]:
    """``{id: "EnumName.Member"}`` for every id PyFLP 2.2.1 defines.

    Imported lazily and guarded: the dump must work even where PyFLP does not.
    """
    names: dict[int, str] = {}
    try:
        import pyflp.arrangement as ar
        import pyflp.channel as ch
        import pyflp.mixer as mx
        import pyflp.pattern as pa
        import pyflp.plugin as pl
        import pyflp.project as pr
        import pyflp.timemarker as tm
    except Exception:  # noqa: BLE001 - names are a nicety
        return names
    for mod in (pr, pa, ch, ar, mx, pl, tm):
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if isinstance(obj, type) and attr.endswith("ID") and hasattr(obj, "__members__"):
                for member in obj:
                    names.setdefault(int(member), f"{attr}.{member.name}")
    return names


def inventory(path: Path) -> dict[str, Any]:
    path = Path(path)
    flp = read_flp(path, strict=False)
    version = nb.fl_version_of(path)
    unicode = nb._version_tuple(version) >= nb.UNICODE_FROM if version else True
    known = pyflp_names()

    rows: dict[int, dict[str, Any]] = {}
    for event in flp.events:
        row = rows.setdefault(event.id, {"id": event.id, "count": 0, "bytes": 0, "preview": None})
        row["count"] += 1
        row["bytes"] += len(event.payload)
        if row["preview"] is None and event.id in PREVIEW_IDS:
            raw = event.payload
            if event.id == nb.FL_VERSION:
                text = raw.decode("ascii", "replace")
            else:
                text = raw[: len(raw) - len(raw) % 2].decode("utf-16-le" if unicode else "latin-1", "replace")
            row["preview"] = text.rstrip("\0")[:40]

    events = []
    for eid in sorted(rows):
        row = rows[eid]
        row["name"] = known.get(eid)
        row["knownToPyflp"] = eid in known
        row["knownToNative"] = eid in nb.KNOWN_IDS
        row["size"] = "1" if eid < 64 else "2" if eid < 128 else "4" if eid < 192 else "var"
        events.append(row)

    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "flVersion": version,
        "newerThanPyflpSupports": nb.newer_than_pyflp_supports(version),
        "eventCount": len(flp.events),
        "truncatedBy": flp.truncated_by,
        "events": events,
        "unknownToPyflp": [e["id"] for e in events if not e["knownToPyflp"]],
        "unknownToNative": [e["id"] for e in events if not e["knownToNative"]],
    }


def as_text(inv: dict[str, Any]) -> str:
    """The inventory as plain text a user can paste."""
    lines = [
        f"PROSODY EVENT INVENTORY  {inv['file']}  ({inv['bytes']} bytes)",
        f"FL version: {inv['flVersion'] or 'not recorded'}"
        + ("  (newer than PyFLP 2.2.1 supports)" if inv["newerThanPyflpSupports"] else ""),
        f"events: {inv['eventCount']}"
        + (f"  truncated by {inv['truncatedBy']} bytes" if inv["truncatedBy"] else ""),
        "",
        f"{'id':>4} {'size':>4} {'count':>6} {'bytes':>8}  {'pyflp':<6} {'name':<30} preview",
    ]
    for e in inv["events"]:
        lines.append(
            f"{e['id']:>4} {e['size']:>4} {e['count']:>6} {e['bytes']:>8}  "
            f"{'yes' if e['knownToPyflp'] else 'NO':<6} {(e['name'] or '-'):<30} "
            f"{e['preview'] or ''}"
        )
    lines.append("")
    lines.append(f"unknown to PyFLP: {inv['unknownToPyflp'] or 'none'}")
    lines.append(f"unknown to native reader: {inv['unknownToNative'] or 'none'}")
    return "\n".join(lines) + "\n"

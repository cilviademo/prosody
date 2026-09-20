"""SQLite library index. Metadata and paths only - never audio or project data.

Migrations are numbered from the start so the schema can move without losing a
user's library.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from prosody_core.model.schemas import HealthStatus, LibraryEntry

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE projects (
            project_id   TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            source_path  TEXT NOT NULL,
            tempo        REAL,
            key          TEXT,
            length_bars  REAL DEFAULT 0,
            genre        TEXT,
            status       TEXT NOT NULL DEFAULT 'Starter',
            health       TEXT NOT NULL DEFAULT 'UNKNOWN',
            out_dir      TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE INDEX idx_projects_updated ON projects(updated_at DESC);
        CREATE TABLE builds (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   TEXT NOT NULL REFERENCES projects(project_id),
            genre        TEXT,
            structure    TEXT,
            level        INTEGER,
            tier         TEXT,
            out_dir      TEXT,
            created_at   TEXT NOT NULL
        );
        CREATE INDEX idx_builds_project ON builds(project_id, created_at DESC);
        """,
    ),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        # A build that is interrupted — the machine sleeps, FL wedges, the
        # user kills Prosody — must not leave a half-written page in the
        # index. WAL keeps readers working during a write and recovers
        # cleanly from a crash (HARDENING P0.2).
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        yield connection
        connection.commit()
    finally:
        connection.close()


class IntegrityResult(NamedTuple):
    ok: bool
    #: Where a corrupt file was moved, when one was.
    quarantined: Path | None
    detail: str


def check_integrity(path: Path) -> IntegrityResult:
    """Verify the index, and set a corrupt one aside rather than failing.

    The index is an index: every row can be rebuilt by rescanning the export
    folder, so a corrupt database is an inconvenience and never a data loss.
    Refusing to start would turn it into one, so a database that cannot be
    read is renamed out of the way and a new one takes its place.
    """
    if not Path(path).is_file():
        return IntegrityResult(True, None, "no database yet")

    try:
        connection = sqlite3.connect(str(path))
        try:
            # quick_check catches the corruption users actually hit at a
            # fraction of integrity_check's cost on a large file.
            row = connection.execute("PRAGMA quick_check").fetchone()
            verdict = row[0] if row else "unknown"
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        verdict = f"unreadable: {exc}"

    if verdict == "ok":
        return IntegrityResult(True, None, "ok")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    quarantine = Path(path).with_name(f"{Path(path).name}.corrupt-{stamp}")
    try:
        Path(path).replace(quarantine)
        # WAL and shared-memory siblings belong to the old database; leaving
        # them behind would corrupt the replacement too.
        for suffix in ("-wal", "-shm"):
            sibling = Path(str(path) + suffix)
            if sibling.exists():
                sibling.replace(Path(str(quarantine) + suffix))
    except OSError as exc:
        return IntegrityResult(False, None, f"{verdict}; it could not be moved aside: {exc}")

    return IntegrityResult(False, quarantine, verdict)


def migrate(path: Path) -> int:
    """Apply pending migrations. Returns the resulting schema version.

    A corrupt database is set aside here rather than raising, so no caller has
    to decide what to do about one. Every entry point goes through migrate, so
    this is the single place that guarantee can live (HARDENING P0.2).
    """
    check_integrity(path)
    with connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        row = db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for version, script in MIGRATIONS:
            if version <= current:
                continue
            db.executescript(script)
            db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, _now()),
            )
            current = version
        return current


def upsert_project(path: Path, entry: LibraryEntry) -> None:
    with connect(path) as db:
        db.execute(
            """
            INSERT INTO projects (project_id, name, source_path, tempo, key,
                                  length_bars, genre, status, health, out_dir,
                                  created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET
                name=excluded.name,
                source_path=excluded.source_path,
                tempo=excluded.tempo,
                key=excluded.key,
                length_bars=excluded.length_bars,
                genre=COALESCE(excluded.genre, projects.genre),
                status=excluded.status,
                health=excluded.health,
                out_dir=COALESCE(excluded.out_dir, projects.out_dir),
                updated_at=excluded.updated_at
            """,
            (
                entry.project_id, entry.name, entry.source_path, entry.tempo,
                entry.key, entry.length_bars, entry.genre, entry.status,
                entry.health.value, entry.out_dir, _now(), _now(),
            ),
        )


def record_build(
    path: Path, project_id: str, *, genre: str | None, structure: str | None,
    level: int, tier: str, out_dir: str,
) -> None:
    with connect(path) as db:
        db.execute(
            "INSERT INTO builds (project_id, genre, structure, level, tier, "
            "out_dir, created_at) VALUES (?,?,?,?,?,?,?)",
            (project_id, genre, structure, level, tier, out_dir, _now()),
        )


def list_projects(path: Path, limit: int = 200) -> list[LibraryEntry]:
    if not Path(path).is_file():
        return []
    with connect(path) as db:
        rows = db.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        LibraryEntry(
            project_id=row["project_id"], name=row["name"],
            source_path=row["source_path"], tempo=row["tempo"], key=row["key"],
            length_bars=row["length_bars"] or 0.0, genre=row["genre"],
            status=row["status"],
            health=HealthStatus(row["health"]) if row["health"] else HealthStatus.UNKNOWN,
            updated_at=datetime.fromisoformat(row["updated_at"]),
            out_dir=row["out_dir"],
        )
        for row in rows
    ]


def get_project(path: Path, project_id: str) -> LibraryEntry | None:
    for entry in list_projects(path, limit=1000):
        if entry.project_id == project_id:
            return entry
    return None


def forget_project(path: Path, project_id: str) -> None:
    """Remove a library row. Never deletes any file on disk."""
    with connect(path) as db:
        db.execute("DELETE FROM builds WHERE project_id = ?", (project_id,))
        db.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))

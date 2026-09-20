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

from flpfinisher.model.schemas import HealthStatus, LibraryEntry

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
        yield connection
        connection.commit()
    finally:
        connection.close()


def migrate(path: Path) -> int:
    """Apply pending migrations. Returns the resulting schema version."""
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

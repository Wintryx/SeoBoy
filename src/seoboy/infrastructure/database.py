"""SQLite connection, migrations, and small database helpers."""

from __future__ import annotations

from contextlib import contextmanager, closing
from importlib.resources import files as resource_files
from pathlib import Path
import sqlite3
from typing import Iterator

MIGRATIONS = ("001_initial.sql", "002_url_inspections.sql")
MIN_SQLITE_VERSION = (3, 38, 0)
SCHEMA_TABLES = {"projects", "sites", "runs", "urls", "run_urls"}


class DatabaseError(ValueError):
    """The database is incompatible or unavailable."""


def _migration_dir() -> Path:
    """Locate SQL migrations both in the source tree and when installed."""
    try:
        candidate = resource_files("seoboy.migrations")
        path = Path(str(candidate))
        if path.is_dir():
            return path
    except (ModuleNotFoundError, TypeError):
        pass
    # Search upward from the module to the project root for the source tree.
    for parent in Path(__file__).resolve().parents:
        fallback = parent / "migrations"
        if fallback.is_dir():
            return fallback
    raise DatabaseError("Die SQL-Migrationen wurden nicht gefunden.")


def connect(path: Path | str) -> sqlite3.Connection:
    target = Path(path)
    connection = sqlite3.connect(target, timeout=10.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    # Local analysis: larger cache and in-memory temporaries.
    connection.execute("PRAGMA cache_size = -32000")
    connection.execute("PRAGMA temp_store = MEMORY")
    try:
        connection.execute("PRAGMA mmap_size = 268435456")
    except sqlite3.OperationalError:
        pass
    return connection


def migrate_database(path: Path | str) -> int:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise DatabaseError(
            f"SQLite {MIN_SQLITE_VERSION[0]}.{MIN_SQLITE_VERSION[1]}."
            f"{MIN_SQLITE_VERSION[2]} oder neuer erforderlich, "
            f"gefunden: {sqlite3.sqlite_version}."
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(target)) as connection:
        try:
            connection.execute("SELECT json_valid('{}')").fetchone()
        except sqlite3.OperationalError as error:
            raise DatabaseError(
                "Die SQLite-Installation unterstützt die JSON-Funktionen nicht."
            ) from error

        (version,) = connection.execute("PRAGMA user_version").fetchone()
        if version > len(MIGRATIONS):
            raise DatabaseError(
                f"Schema-Version {version} ist neuer als diese SeoBoy-Version "
                f"({len(MIGRATIONS)}). Bitte SeoBoy aktualisieren."
            )

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type = 'table' AND name NOT GLOB 'sqlite_*'"
            )
        }
        if version == 0 and tables:
            raise DatabaseError(
                "Die Datenbank enthält bereits Tabellen ohne SeoBoy-Schema-Version."
            )
        if version and not SCHEMA_TABLES.issubset(tables):
            raise DatabaseError(
                "Die vorhandene Datenbank enthält kein gültiges SeoBoy-Schema."
            )

        scripts = _migration_dir()
        for filename in MIGRATIONS[version:]:
            script = (scripts / filename).read_text(encoding="utf-8")
            try:
                connection.executescript(script)
            except sqlite3.Error:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
                raise
            (version,) = connection.execute("PRAGMA user_version").fetchone()
            expected = int(filename.split("_", 1)[0])
            if version != expected:
                raise DatabaseError(
                    f"{filename} hat Schema-Version {version} statt {expected} gesetzt."
                )
        return version


def schema_version(connection: sqlite3.Connection) -> int:
    (version,) = connection.execute("PRAGMA user_version").fetchone()
    return int(version)


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Short, exclusive write transaction (BEGIN IMMEDIATE)."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def next_id(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    run_id: str | None = None,
) -> int:
    if table not in {
        "source_imports",
        "url_discoveries",
        "crawl_jobs",
        "http_attempts",
        "page_observations",
        "gsc_datasets",
    }:
        raise DatabaseError(f"Unbekannte ID-Tabelle: {table}")
    if run_id is None:
        query = f"SELECT COALESCE(MAX({column}), 0) + 1 FROM {table}"  # noqa: S608
        (value,) = connection.execute(query).fetchone()
    else:
        query = (
            f"SELECT COALESCE(MAX({column}), 0) + 1 FROM {table} WHERE run_id = ?"  # noqa: S608
        )
        (value,) = connection.execute(query, (run_id,)).fetchone()
    return int(value)


def ensure_project(
    connection: sqlite3.Connection, project_id: str, name: str | None = None
) -> None:
    connection.execute(
        "INSERT INTO projects(project_id, name) VALUES (?, ?) "
        "ON CONFLICT(project_id) DO NOTHING",
        (project_id, name or project_id),
    )


def ensure_site(
    connection: sqlite3.Connection,
    project_id: str,
    site_id: str,
    start_url: str,
) -> None:
    connection.execute(
        "INSERT INTO sites(project_id, site_id, role, label, start_url) "
        "VALUES (?, ?, 'own', ?, ?) "
        "ON CONFLICT(project_id, site_id) DO UPDATE SET start_url = excluded.start_url",
        (project_id, site_id, project_id, start_url),
    )


def ensure_schema(connection: sqlite3.Connection) -> None:
    if schema_version(connection) != len(MIGRATIONS):
        raise DatabaseError(
            "Die Datenbank wurde noch nicht migriert. Bitte 'seoboy migrate' ausführen."
        )


def count_attempts(connection: sqlite3.Connection, run_id: str) -> int:
    (count,) = connection.execute(
        "SELECT COUNT(*) FROM http_attempts WHERE run_id = ?", (run_id,)
    ).fetchone()
    return int(count)


def count_admitted(connection: sqlite3.Connection, run_id: str) -> int:
    (count,) = connection.execute(
        "SELECT COUNT(*) FROM run_urls WHERE run_id = ? AND admitted_at IS NOT NULL",
        (run_id,),
    ).fetchone()
    return int(count)
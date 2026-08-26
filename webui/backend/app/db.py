"""SQLite storage for jobs and uploaded assets.

The worker thread and the request handlers share one connection, so every
statement goes through a lock: sqlite3 allows cross-thread use but not
concurrent use. One writer, one job at a time — no server is needed.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    state         TEXT NOT NULL DEFAULT 'queued',
    prompt        TEXT NOT NULL DEFAULT '',
    params        TEXT NOT NULL,
    argv          TEXT,
    phase         TEXT,
    completed     INTEGER NOT NULL DEFAULT 0,
    total         INTEGER NOT NULL DEFAULT 0,
    progress      REAL NOT NULL DEFAULT 0.0,
    error         TEXT,
    output_path   TEXT,
    log_path      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    started_at    TEXT,
    finished_at   TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256        TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL,
    filename      TEXT NOT NULL,
    path          TEXT NOT NULL,
    bytes         INTEGER NOT NULL,
    metadata      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Closed(RuntimeError):
    """The database was closed while a background thread was still writing."""


class Database:
    """Every access is serialized and returns plain rows, never live cursors."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._open = True
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._connection.executescript(SCHEMA)
            self._connection.commit()

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._guard() as connection:
            return connection.execute(sql, params).fetchone()

    def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._guard() as connection:
            return connection.execute(sql, params).fetchall()

    def run(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._guard() as connection:
            cursor = connection.execute(sql, params)
            connection.commit()
            return int(cursor.lastrowid or 0)

    def close(self) -> None:
        with self._lock:
            if self._open:
                self._open = False
                self._connection.close()

    def _guard(self):
        database = self

        class _Guard:
            def __enter__(self) -> sqlite3.Connection:
                database._lock.acquire()
                if not database._open:
                    database._lock.release()
                    raise Closed("the database is closed")
                return database._connection

            def __exit__(self, *_: object) -> bool:
                database._lock.release()
                return False

        return _Guard()

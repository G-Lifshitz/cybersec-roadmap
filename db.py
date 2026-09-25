import sqlite3
import os

DB_PATH = os.environ.get("DATA_DIR", ".") + "/roadmap.db"


class _DatabaseManager:
    """
    Singleton that owns the SQLite connection for this process.

    Pattern: Singleton (Creational)
    Ensures only one connection object is ever created, giving every caller the
    same handle and eliminating repeated connect/close overhead.  Safe for our
    use-case: single-user Flask app, single process, single thread per request
    (Werkzeug dev server default).  check_same_thread=False lets the connection
    be handed to request threads without SQLite raising an error.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._conn = None
        return cls._instance

    def connection(self):
        """Return the shared connection, creating it on first call."""
        if self._conn is None:
            self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn


_db_manager = _DatabaseManager()


def get_db():
    """Return the singleton database connection.

    Used as a context manager by model functions::

        with get_db() as conn:
            conn.execute(...)

    The context manager commits on success and rolls back on exception;
    it does *not* close the connection (SQLite connection.__exit__ semantics).
    """
    return _db_manager.connection()


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS roadmap_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                type        TEXT NOT NULL,
                platform    TEXT,
                url         TEXT,
                skill_tags  TEXT,
                difficulty  TEXT DEFAULT 'beginner',
                priority    INTEGER DEFAULT 3,
                status      TEXT DEFAULT 'not_started',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS progress_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id         INTEGER NOT NULL REFERENCES roadmap_items(id) ON DELETE CASCADE,
                checked_in_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completion_pct  INTEGER DEFAULT 0,
                felt_difficulty TEXT,
                notes           TEXT,
                time_spent_mins INTEGER
            );
        """)

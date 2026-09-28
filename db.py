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
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS roadmap_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
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

            CREATE TABLE IF NOT EXISTS rate_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                kind       TEXT NOT NULL,   -- 'login_fail', 'login_fail_ip', 'register'
                key        TEXT NOT NULL,   -- who it's counted against (username|ip, or ip)
                created_at REAL NOT NULL    -- unix time, seconds
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
        _migrate(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_user ON roadmap_items(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rate_lookup ON rate_events(kind, key, created_at)"
        )


def _migrate(conn):
    """Bring a database created before accounts existed up to date.

    CREATE TABLE IF NOT EXISTS won't add a column to a table that's already
    there, so older roadmap.db files need user_id added by hand. Items created
    before this migration have user_id NULL and belong to nobody.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(roadmap_items)")}
    if "user_id" not in cols:
        conn.execute(
            "ALTER TABLE roadmap_items ADD COLUMN user_id INTEGER "
            "REFERENCES users(id) ON DELETE CASCADE"
        )

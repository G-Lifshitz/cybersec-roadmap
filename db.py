import sqlite3
import os

DB_PATH = os.environ.get("DATA_DIR", ".") + "/roadmap.db"


class _DatabaseManager:
    """
    Singleton that owns the SQLite connection for this process.

    Pattern: Singleton (Creational)
    Only one connection object is ever created, so every caller shares the same
    handle and there is no connect/close overhead per query. The app has many
    users but runs as one process, and Werkzeug serves each request in a
    thread; check_same_thread=False lets those threads use the connection.

    Trade-off: every request shares this one connection, so transactions from
    requests that overlap in time are not isolated from each other. That is
    fine at this app's scale; under real concurrent load the next step would
    be one connection per request (stored on Flask's g).
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
            # A DATA_DIR that doesn't exist yet (e.g. a fresh volume) is created,
            # so the first start never fails with "unable to open database file".
            os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
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
                is_admin      INTEGER NOT NULL DEFAULT 0,
                session_epoch INTEGER NOT NULL DEFAULT 0,  -- bumped on password change; old cookies stop working
                path_field    TEXT,      -- chosen career field (key in services/timeline_catalog.py)
                path_level    TEXT,      -- none | beginner | intermediate | advanced
                github_username TEXT,    -- linked public GitHub profile (no token stored)
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS login_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                success    INTEGER NOT NULL,          -- 1 = logged in, 0 = wrong password
                ip         TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

            CREATE TABLE IF NOT EXISTS assessments (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                field     TEXT NOT NULL,     -- key in services/question_bank.py
                answers   TEXT NOT NULL,     -- JSON {question_id: option_index}
                score     INTEGER NOT NULL,
                max_score INTEGER NOT NULL,
                level     TEXT NOT NULL,     -- none | beginner | intermediate | advanced
                taken_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_login_events_user ON login_events(user_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_assessments_user ON assessments(user_id, id)"
        )


def _migrate(conn):
    """Bring a database created by an older version of the app up to date.

    CREATE TABLE IF NOT EXISTS won't add a column to a table that's already
    there, so columns added after launch are added here if missing. Items
    created before accounts existed have user_id NULL and belong to nobody.
    """
    added_columns = [
        ("roadmap_items", "user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE"),
        ("users", "is_admin", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "session_epoch", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "path_field", "TEXT"),
        ("users", "path_level", "TEXT"),
        ("users", "github_username", "TEXT"),
    ]
    # Table/column names here are fixed strings from the list above, never input.
    for table, column, definition in added_columns:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

import sqlite3
import os

DB_PATH = os.environ.get("DATA_DIR", ".") + "/roadmap.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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

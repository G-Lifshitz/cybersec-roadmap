"""Sliding-window rate limiting stored in SQLite.

Every attempt worth limiting (a failed login, a sign-up) is written to the
rate_events table as (kind, key, timestamp). To decide whether to block, we
count that key's events inside the last `window` seconds.

Why SQLite and not an in-memory dict: counters survive a restart (restarting
the app shouldn't hand an attacker a fresh set of guesses), and it keeps the
single-process, no-Redis constraint from the assignment.

`now` is a parameter on every function so tests can move the clock without
sleeping.
"""
import time

from db import get_db


def record(kind, key, now=None):
    now = time.time() if now is None else now
    with get_db() as conn:
        conn.execute(
            "INSERT INTO rate_events (kind, key, created_at) VALUES (?, ?, ?)",
            (kind, key, now),
        )


def count_recent(kind, key, window, now=None):
    now = time.time() if now is None else now
    with get_db() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM rate_events
               WHERE kind = ? AND key = ? AND created_at > ?""",
            (kind, key, now - window),
        ).fetchone()
    return row["n"]


def is_limited(kind, key, limit, window, now=None):
    """True once `key` has `limit` or more events of this kind in the window."""
    return count_recent(kind, key, window, now) >= limit


def retry_after(kind, key, window, now=None):
    """Seconds until the oldest event in the window expires (0 if not limited)."""
    now = time.time() if now is None else now
    with get_db() as conn:
        row = conn.execute(
            """SELECT MIN(created_at) AS oldest FROM rate_events
               WHERE kind = ? AND key = ? AND created_at > ?""",
            (kind, key, now - window),
        ).fetchone()
    if row["oldest"] is None:
        return 0
    return max(0, int(row["oldest"] + window - now) + 1)


def clear(kind, key):
    """Forget a key's history, e.g. after a successful login."""
    with get_db() as conn:
        conn.execute("DELETE FROM rate_events WHERE kind = ? AND key = ?", (kind, key))


def prune(older_than, now=None):
    """Delete events older than `older_than` seconds so the table doesn't grow forever."""
    now = time.time() if now is None else now
    with get_db() as conn:
        conn.execute("DELETE FROM rate_events WHERE created_at < ?", (now - older_than,))


def clear_kinds(*kinds):
    """Remove every event of the given kinds (admin 'clear lockouts' button). Returns rows removed."""
    placeholders = ", ".join("?" for _ in kinds)
    with get_db() as conn:
        cur = conn.execute(f"DELETE FROM rate_events WHERE kind IN ({placeholders})", kinds)
        return cur.rowcount


def active_lockouts(kind, limit, window, now=None):
    """Keys that are currently over the limit, with their failure counts."""
    now = time.time() if now is None else now
    with get_db() as conn:
        return conn.execute(
            """SELECT key, COUNT(*) AS n FROM rate_events
               WHERE kind = ? AND created_at > ?
               GROUP BY key HAVING COUNT(*) >= ?
               ORDER BY n DESC""",
            (kind, now - window, limit),
        ).fetchall()

"""Sliding-window rate limiting stored in the roadmap database.

Every attempt worth limiting (a failed login, a sign-up) is written to
rate_events as (kind, key, unix time). To decide whether to block, we count
that key's events inside the last `window` seconds.

Counters live in the database rather than in memory because the container
scales to zero: an in-memory dict would hand an attacker a fresh set of
guesses after every idle period. A message broker or Redis is out of scope
for this assignment (§1c).

`now` is a parameter on every function so tests can move the clock.
"""
import time

from db import transaction


def _now(now):
    return time.time() if now is None else now


def record(kind, key, now=None):
    with transaction() as cur:
        cur.execute("INSERT INTO rate_events (kind, [key], created_at) VALUES (%s, %s, %s)",
                    (kind, key, _now(now)))


def count_recent(kind, key, window, now=None):
    with transaction() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM rate_events WHERE kind = %s AND [key] = %s AND created_at > %s",
                    (kind, key, _now(now) - window))
        return cur.fetchone()["n"]


def is_limited(kind, key, limit, window, now=None):
    """True once `key` has `limit` or more events of this kind in the window."""
    return count_recent(kind, key, window, now) >= limit


def retry_after(kind, key, window, now=None):
    """Seconds until the oldest event in the window expires (0 if there are none)."""
    now = _now(now)
    with transaction() as cur:
        cur.execute("""SELECT MIN(created_at) AS oldest FROM rate_events
                       WHERE kind = %s AND [key] = %s AND created_at > %s""",
                    (kind, key, now - window))
        oldest = cur.fetchone()["oldest"]
    if oldest is None:
        return 0
    return max(0, int(oldest + window - now) + 1)


def clear(kind, key):
    """Forget a key's history, e.g. after a successful login."""
    with transaction() as cur:
        cur.execute("DELETE FROM rate_events WHERE kind = %s AND [key] = %s", (kind, key))


def prune(older_than, now=None):
    """Delete events older than `older_than` seconds so the table doesn't grow forever."""
    with transaction() as cur:
        cur.execute("DELETE FROM rate_events WHERE created_at < %s", (_now(now) - older_than,))

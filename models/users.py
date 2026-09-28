"""Accounts: registration and login.

Passwords are never stored. generate_password_hash() produces a salted
scrypt hash (Werkzeug's default), and check_password_hash() re-hashes the
login attempt with the same salt and compares in constant time.
"""
import re
import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
MIN_PASSWORD_LEN = 8


class RegistrationError(ValueError):
    """Raised with a user-facing message when sign-up input is rejected."""


def create_user(username, password):
    """Create an account and return its id. Raises RegistrationError on bad input."""
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise RegistrationError("Username must be 3-30 characters: letters, numbers or underscores.")
    if len(password or "") < MIN_PASSWORD_LEN:
        raise RegistrationError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")

    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        # UNIQUE COLLATE NOCASE on username: "Georgy" and "georgy" collide
        raise RegistrationError("That username is already taken.")


def authenticate(username, password):
    """Return the user row if the credentials are right, otherwise None.

    Same None for "no such user" and "wrong password", so the login page
    can't be used to find out which usernames exist.
    """
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", ((username or "").strip(),)
        ).fetchone()
    if user and check_password_hash(user["password_hash"], password or ""):
        return user
    return None


def get_by_id(user_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT id, username, is_admin, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()


# ── Admin ──────────────────────────────────────────────────────────────────

def ensure_admin(username, password):
    """Make sure an admin account exists. Called at startup from env vars.

    - no such user: create it (same validation as normal sign-up) as admin
    - user exists:  promote to admin, leave the password alone

    Returns the admin's id, or None if username/password weren't provided.
    """
    if not username or not password:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    user_id = row["id"] if row else create_user(username, password)
    with get_db() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
    return user_id


def list_with_stats():
    """Every user with item/log counts and total minutes — for the admin panel.

    Note what's NOT selected: password_hash, and the content of anyone's roadmap.
    """
    with get_db() as conn:
        return conn.execute(
            """SELECT u.id, u.username, u.is_admin, u.created_at,
                      COUNT(DISTINCT ri.id)            AS items,
                      COUNT(pl.id)                     AS logs,
                      COALESCE(SUM(pl.time_spent_mins), 0) AS minutes,
                      MAX(pl.checked_in_at)            AS last_active
               FROM users u
               LEFT JOIN roadmap_items ri ON ri.user_id = u.id
               LEFT JOIN progress_logs pl ON pl.item_id = ri.id
               GROUP BY u.id
               ORDER BY u.created_at"""
        ).fetchall()


def delete_user(user_id):
    """Delete an account; ON DELETE CASCADE removes their items and logs too."""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0

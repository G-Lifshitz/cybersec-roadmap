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


class AccountError(ValueError):
    """Raised with a user-facing message when account input is rejected."""


class RegistrationError(AccountError):
    """Sign-up specifically (bad username, weak password, name taken)."""


def _check_password_rules(password, error=AccountError):
    if len(password or "") < MIN_PASSWORD_LEN:
        raise error(f"Password must be at least {MIN_PASSWORD_LEN} characters.")


def create_user(username, password):
    """Create an account and return its id. Raises RegistrationError on bad input."""
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise RegistrationError("Username must be 3-30 characters: letters, numbers or underscores.")
    _check_password_rules(password, RegistrationError)

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
            """SELECT id, username, is_admin, session_epoch, path_field, path_level, github_username, created_at
               FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()


def set_github_username(user_id, github_username):
    """Link (or with None, unlink) a public GitHub profile. The caller validates the name."""
    with get_db() as conn:
        conn.execute("UPDATE users SET github_username = ? WHERE id = ?", (github_username, user_id))


def set_path(user_id, field, level):
    """Remember which career field and level the user's timeline is built for.

    The caller validates field and level against the catalogue; this only stores them.
    """
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET path_field = ?, path_level = ? WHERE id = ?", (field, level, user_id)
        )


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



# ── Account settings ───────────────────────────────────────────────────────

def _password_matches(user_id, password):
    with get_db() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row) and check_password_hash(row["password_hash"], password or "")


def change_password(user_id, current, new):
    """Replace the password after re-checking the current one.

    Also bumps session_epoch, which invalidates every other logged-in session
    (a stolen cookie stops working once the owner changes their password).
    Returns the new epoch so the caller can keep the current session alive.
    """
    if not _password_matches(user_id, current):
        raise AccountError("Current password is wrong.")
    _check_password_rules(new)
    if current == new:
        raise AccountError("New password must be different from the current one.")
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 WHERE id = ?",
            (generate_password_hash(new), user_id),
        )
        return conn.execute(
            "SELECT session_epoch FROM users WHERE id = ?", (user_id,)
        ).fetchone()["session_epoch"]


def delete_account(user_id, password):
    """Self-service account deletion (GDPR right to erasure).

    Needs the password, so an unattended logged-in laptop can't be used to
    wipe someone's data. ON DELETE CASCADE removes items, logs and login events.
    The last remaining admin can't delete themselves (nobody could manage the app).
    """
    if not _password_matches(user_id, password):
        raise AccountError("Password is wrong.")
    with get_db() as conn:
        user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if user["is_admin"]:
            admins = conn.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin = 1").fetchone()["n"]
            if admins <= 1:
                raise AccountError("You're the only admin, so this account can't be deleted.")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ── Login history ──────────────────────────────────────────────────────────

def export_account(user_id):
    """Account details for the data export. password_hash and session_epoch are left out on purpose."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT username, is_admin, github_username, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def all_logins(user_id):
    """Every sign-in event for this user, oldest first (used by the data export)."""
    with get_db() as conn:
        return conn.execute(
            "SELECT success, ip, created_at FROM login_events WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()


def get_id_by_username(username):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", ((username or "").strip(),)
        ).fetchone()
    return row["id"] if row else None


def record_login(user_id, success, ip):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO login_events (user_id, success, ip) VALUES (?, ?, ?)",
            (user_id, 1 if success else 0, ip),
        )


def recent_logins(user_id, limit=10):
    """Newest first. id DESC breaks ties between events in the same second."""
    with get_db() as conn:
        return conn.execute(
            """SELECT success, ip, created_at FROM login_events
               WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()


def failed_since_last_login(user_id):
    """Failed attempts after the previous successful login (call before recording the new one).

    Shown as a warning when someone logs in: "3 failed attempts since your last login".
    """
    with get_db() as conn:
        last_ok = conn.execute(
            "SELECT MAX(id) AS id FROM login_events WHERE user_id = ? AND success = 1",
            (user_id,),
        ).fetchone()["id"] or 0
        return conn.execute(
            "SELECT COUNT(*) AS n FROM login_events WHERE user_id = ? AND success = 0 AND id > ?",
            (user_id, last_ok),
        ).fetchone()["n"]

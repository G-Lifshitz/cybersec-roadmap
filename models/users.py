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
            "SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()

"""Accounts: registration, login, password change, deletion and login history.

Passwords are never stored: generate_password_hash() makes a salted scrypt
hash (Werkzeug's default) and check_password_hash() compares in constant time.
"""
import re

from werkzeug.security import check_password_hash, generate_password_hash

from db import IntegrityError, transaction

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 200   # scrypt on a megabyte-long "password" is a cheap DoS

_PUBLIC = "id, username, is_admin, session_epoch, path_field, path_level, github_username, created_at"


class AccountError(ValueError):
    """Raised with a user-facing message when account input is rejected."""


class RegistrationError(AccountError):
    """Sign-up specifically (bad username, weak password, name taken)."""


def _check_password_rules(password, error=AccountError):
    if len(password or "") < MIN_PASSWORD_LEN:
        raise error(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(password) > MAX_PASSWORD_LEN:
        raise error(f"Password must be at most {MAX_PASSWORD_LEN} characters.")


def create_user(username, password):
    """Create an account and return its id. Raises RegistrationError on bad input."""
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise RegistrationError("Username must be 3-30 characters: letters, numbers or underscores.")
    _check_password_rules(password, RegistrationError)
    try:
        with transaction() as cur:
            cur.execute("INSERT INTO users (username, password_hash) OUTPUT INSERTED.id VALUES (%s, %s)",
                        (username, generate_password_hash(password)))
            return cur.fetchone()["id"]
    except IntegrityError:
        # The username column is case-insensitive: "Georgy" and "georgy" collide.
        raise RegistrationError("That username is already taken.") from None


def authenticate(username, password):
    """The user row if the credentials are right, otherwise None.

    Same None for "no such user" and "wrong password", so login can't be used
    to find out which usernames exist.
    """
    with transaction() as cur:
        cur.execute(f"SELECT {_PUBLIC}, password_hash FROM users WHERE username = %s",
                    ((username or "").strip(),))
        user = cur.fetchone()
    if user and check_password_hash(user["password_hash"], (password or "")[:MAX_PASSWORD_LEN]):
        user.pop("password_hash")
        return user
    return None


def get_by_id(user_id):
    with transaction() as cur:
        cur.execute(f"SELECT {_PUBLIC} FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


def get_id_by_username(username):
    with transaction() as cur:
        cur.execute("SELECT id FROM users WHERE username = %s", ((username or "").strip(),))
        row = cur.fetchone()
    return row["id"] if row else None


def set_path(user_id, field, level):
    """Store the career field and level the timeline is built for (caller validates them)."""
    with transaction() as cur:
        cur.execute("UPDATE users SET path_field = %s, path_level = %s WHERE id = %s",
                    (field, level, user_id))


def _password_matches(user_id, password):
    with transaction() as cur:
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    return bool(row) and check_password_hash(row["password_hash"], (password or "")[:MAX_PASSWORD_LEN])


def change_password(user_id, current, new):
    """Replace the password after re-checking the current one.

    Bumps session_epoch, which invalidates every token issued before (a stolen
    token stops working once the owner changes their password). Returns the
    new epoch so the caller can issue a fresh token for this session.
    """
    if not _password_matches(user_id, current):
        raise AccountError("Current password is wrong.")
    _check_password_rules(new)
    if current == new:
        raise AccountError("New password must be different from the current one.")
    with transaction() as cur:
        cur.execute("""UPDATE users SET password_hash = %s, session_epoch = session_epoch + 1
                       OUTPUT INSERTED.session_epoch WHERE id = %s""",
                    (generate_password_hash(new), user_id))
        return cur.fetchone()["session_epoch"]


def check_can_delete(user_id, password):
    """Raise AccountError unless this user may delete their own account now.

    Needs the password, so an unattended logged-in laptop can't be used to wipe
    someone's data. The last remaining admin can't delete themselves.
    """
    if not _password_matches(user_id, password):
        raise AccountError("Password is wrong.")
    with transaction() as cur:
        cur.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if user and user["is_admin"]:
            cur.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin = 1")
            if cur.fetchone()["n"] <= 1:
                raise AccountError("You're the only admin, so this account can't be deleted.")


def delete_user(user_id):
    """Delete the account; ON DELETE CASCADE removes items, assessments and login events."""
    with transaction() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return cur.rowcount > 0


def record_login(user_id, success, ip):
    with transaction() as cur:
        cur.execute("INSERT INTO login_events (user_id, success, ip) VALUES (%s, %s, %s)",
                    (user_id, 1 if success else 0, ip))


def recent_logins(user_id, limit=10):
    """Newest first. id DESC breaks ties between events in the same instant."""
    with transaction() as cur:
        cur.execute("""SELECT TOP (%s) success, ip, created_at FROM login_events
                       WHERE user_id = %s ORDER BY id DESC""", (int(limit), user_id))
        return cur.fetchall()


def failed_since_last_login(user_id):
    """Failed attempts after the previous successful login (call before recording the new one)."""
    with transaction() as cur:
        cur.execute("SELECT MAX(id) AS id FROM login_events WHERE user_id = %s AND success = 1",
                    (user_id,))
        last_ok = cur.fetchone()["id"] or 0
        cur.execute("SELECT COUNT(*) AS n FROM login_events WHERE user_id = %s AND success = 0 AND id > %s",
                    (user_id, last_ok))
        return cur.fetchone()["n"]

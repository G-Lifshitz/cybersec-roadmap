import os
import tempfile
import pytest

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATA_DIR"] = os.path.dirname(tmp.name)

import db
import models.roadmap as roadmap
import models.users as users

db.DB_PATH = tmp.name


@pytest.fixture(autouse=True)
def fresh_db():
    db.init_db()
    yield
    with db.get_db() as conn:
        conn.executescript("DELETE FROM progress_logs; DELETE FROM roadmap_items; DELETE FROM users;")


def test_create_and_authenticate():
    uid = users.create_user("georgy", "s3cure-pass")
    user = users.authenticate("georgy", "s3cure-pass")
    assert user is not None
    assert user["id"] == uid


def test_password_is_hashed_not_stored():
    users.create_user("georgy", "s3cure-pass")
    with db.get_db() as conn:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()["password_hash"]
    assert "s3cure-pass" not in stored
    assert stored.startswith(("scrypt:", "pbkdf2:"))  # Werkzeug hash format


def test_same_password_gets_different_hashes():
    # Salting: two users with the same password must not share a hash
    users.create_user("user_a", "same-password")
    users.create_user("user_b", "same-password")
    with db.get_db() as conn:
        hashes = [r["password_hash"] for r in conn.execute("SELECT password_hash FROM users")]
    assert hashes[0] != hashes[1]


def test_wrong_password_and_unknown_user_both_return_none():
    users.create_user("georgy", "s3cure-pass")
    assert users.authenticate("georgy", "wrong-pass") is None
    assert users.authenticate("nobody", "s3cure-pass") is None


def test_duplicate_username_rejected_case_insensitively():
    users.create_user("Georgy", "s3cure-pass")
    with pytest.raises(users.RegistrationError, match="taken"):
        users.create_user("georgy", "other-pass1")


@pytest.mark.parametrize("name", ["ab", "has space", "x" * 31, "semi;colon", ""])
def test_bad_usernames_rejected(name):
    with pytest.raises(users.RegistrationError, match="Username"):
        users.create_user(name, "s3cure-pass")


def test_short_password_rejected():
    with pytest.raises(users.RegistrationError, match="Password"):
        users.create_user("georgy", "short")


def test_get_by_id_does_not_expose_hash():
    uid = users.create_user("georgy", "s3cure-pass")
    user = users.get_by_id(uid)
    assert user["username"] == "georgy"
    assert "password_hash" not in user.keys()


def test_deleting_user_deletes_their_items():
    uid = users.create_user("georgy", "s3cure-pass")
    item_id = roadmap.create(uid, "PEH", "course", "", "", "web", "beginner", 3)
    with db.get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    assert roadmap.get_by_id(item_id, uid) is None  # removed by ON DELETE CASCADE


@pytest.mark.parametrize("payload", ["' OR '1'='1", "admin' --", "' OR 1=1 --"])
def test_login_injection_does_not_bypass_auth(payload):
    users.create_user("georgy", "s3cure-pass")
    assert users.authenticate(payload, "anything") is None
    assert users.authenticate("georgy", payload) is None


# ── Admin ───────────────────────────────────────────────────────────────────

def test_ensure_admin_creates_admin_account():
    uid = users.ensure_admin("root_admin", "admin-pass-123")
    assert users.get_by_id(uid)["is_admin"] == 1
    assert users.authenticate("root_admin", "admin-pass-123") is not None


def test_ensure_admin_promotes_existing_user_without_changing_password():
    uid = users.create_user("georgy", "original-pass")
    assert users.ensure_admin("georgy", "different-pass") == uid
    assert users.get_by_id(uid)["is_admin"] == 1
    assert users.authenticate("georgy", "original-pass") is not None


def test_ensure_admin_is_idempotent_and_skips_when_unset():
    first = users.ensure_admin("root_admin", "admin-pass-123")
    assert users.ensure_admin("root_admin", "admin-pass-123") == first
    assert users.ensure_admin(None, None) is None
    assert users.ensure_admin("root_admin", "") is None


def test_normal_signups_are_not_admin():
    uid = users.create_user("georgy", "s3cure-pass")
    assert users.get_by_id(uid)["is_admin"] == 0


def test_list_with_stats_counts_and_hides_hashes():
    import models.progress as progress
    a = users.create_user("alice", "password-a")
    users.create_user("bob", "password-b")
    item = roadmap.create(a, "PEH", "course", "", "", "web", "beginner", 3)
    progress.add_log(item, 50, "fair", "", 90)
    progress.add_log(item, 70, "hard", "", 30)
    rows = {r["username"]: r for r in users.list_with_stats()}
    assert (rows["alice"]["items"], rows["alice"]["logs"], rows["alice"]["minutes"]) == (1, 2, 120)
    assert (rows["bob"]["items"], rows["bob"]["logs"], rows["bob"]["minutes"]) == (0, 0, 0)
    assert "password_hash" not in rows["alice"].keys()


def test_delete_user():
    uid = users.create_user("georgy", "s3cure-pass")
    assert users.delete_user(uid) is True
    assert users.get_by_id(uid) is None
    assert users.delete_user(uid) is False


# ── Account settings ────────────────────────────────────────────────────────

def test_change_password_works_and_bumps_epoch():
    uid = users.create_user("georgy", "old-password")
    before = users.get_by_id(uid)["session_epoch"]
    new_epoch = users.change_password(uid, "old-password", "new-password")
    assert new_epoch == before + 1
    assert users.authenticate("georgy", "new-password") is not None
    assert users.authenticate("georgy", "old-password") is None


@pytest.mark.parametrize("current, new, msg", [
    ("wrong-password", "new-password", "Current password is wrong"),
    ("old-password", "short", "at least 8"),
    ("old-password", "old-password", "must be different"),
])
def test_change_password_rejections(current, new, msg):
    uid = users.create_user("georgy", "old-password")
    with pytest.raises(users.AccountError, match=msg):
        users.change_password(uid, current, new)
    assert users.get_by_id(uid)["session_epoch"] == 0  # nothing changed
    assert users.authenticate("georgy", "old-password") is not None


def test_registration_error_is_an_account_error():
    assert issubclass(users.RegistrationError, users.AccountError)


def test_delete_account_needs_password_and_wipes_data():
    import models.progress as progress
    uid = users.create_user("georgy", "s3cure-pass")
    item = roadmap.create(uid, "PEH", "course", "", "", "web", "beginner", 3)
    progress.add_log(item, 50, "fair", "", 60)
    users.record_login(uid, True, "1.1.1.1")

    with pytest.raises(users.AccountError, match="Password is wrong"):
        users.delete_account(uid, "nope")
    assert users.get_by_id(uid) is not None

    users.delete_account(uid, "s3cure-pass")
    assert users.get_by_id(uid) is None
    with db.get_db() as conn:
        for table in ("roadmap_items", "progress_logs", "login_events"):
            assert conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0


def test_last_admin_cannot_delete_self_but_one_of_two_can():
    a = users.ensure_admin("admin_one", "admin-pass-1")
    with pytest.raises(users.AccountError, match="only admin"):
        users.delete_account(a, "admin-pass-1")
    b = users.ensure_admin("admin_two", "admin-pass-2")
    users.delete_account(b, "admin-pass-2")
    assert users.get_by_id(b) is None


# ── Login history ───────────────────────────────────────────────────────────

def test_recent_logins_newest_first_and_private():
    a = users.create_user("alice", "password-a")
    b = users.create_user("bob", "password-b")
    users.record_login(a, False, "6.6.6.6")
    users.record_login(a, True, "1.2.3.4")
    users.record_login(b, True, "9.9.9.9")
    rows = users.recent_logins(a)
    assert [(r["success"], r["ip"]) for r in rows] == [(1, "1.2.3.4"), (0, "6.6.6.6")]
    assert users.recent_logins(a, limit=1)[0]["ip"] == "1.2.3.4"


def test_failed_since_last_login():
    uid = users.create_user("alice", "password-a")
    assert users.failed_since_last_login(uid) == 0
    users.record_login(uid, False, "x")          # before any success
    assert users.failed_since_last_login(uid) == 1
    users.record_login(uid, True, "x")
    assert users.failed_since_last_login(uid) == 0
    users.record_login(uid, False, "x")
    users.record_login(uid, False, "x")
    assert users.failed_since_last_login(uid) == 2


def test_get_id_by_username():
    uid = users.create_user("Georgy", "s3cure-pass")
    assert users.get_id_by_username("georgy") == uid   # NOCASE
    assert users.get_id_by_username("nobody") is None


def test_new_user_has_no_path_until_one_is_set():
    uid = users.create_user("pathfinder", "s3cure-pass")
    assert users.get_by_id(uid)["path_field"] is None
    users.set_path(uid, "soc", "beginner")
    user = users.get_by_id(uid)
    assert (user["path_field"], user["path_level"]) == ("soc", "beginner")

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

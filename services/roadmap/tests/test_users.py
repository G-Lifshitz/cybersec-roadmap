"""Accounts model against SQL Server."""
import pytest

import db
import models.roadmap as roadmap
import models.users as users

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _clean(clean_db):
    pass


def test_create_and_authenticate():
    uid = users.create_user("georgy", "s3cure-pass")
    user = users.authenticate("georgy", "s3cure-pass")
    assert user["id"] == uid
    assert "password_hash" not in user


def test_password_is_hashed_and_salted():
    users.create_user("a_user", "same-password")
    users.create_user("b_user", "same-password")
    with db.transaction() as cur:
        cur.execute("SELECT password_hash FROM users")
        hashes = [r["password_hash"] for r in cur.fetchall()]
    assert all("same-password" not in h for h in hashes)
    assert hashes[0] != hashes[1]


def test_wrong_password_and_unknown_user_both_return_none():
    users.create_user("georgy", "s3cure-pass")
    assert users.authenticate("georgy", "wrong-pass") is None
    assert users.authenticate("nobody", "s3cure-pass") is None


def test_duplicate_username_rejected_case_insensitively():
    users.create_user("Georgy", "s3cure-pass")
    with pytest.raises(users.RegistrationError, match="taken"):
        users.create_user("georgy", "other-pass1")


@pytest.mark.parametrize("payload", ["' OR '1'='1", "admin'--", "x'; DROP TABLE users; --"])
def test_login_injection_does_not_bypass_auth(payload):
    users.create_user("georgy", "s3cure-pass")
    assert users.authenticate(payload, payload) is None
    assert users.get_id_by_username("georgy") is not None   # table still there


def test_change_password_bumps_epoch_and_rejects_wrong_current():
    uid = users.create_user("georgy", "s3cure-pass")
    with pytest.raises(users.AccountError, match="wrong"):
        users.change_password(uid, "nope", "new-pass-123")
    assert users.change_password(uid, "s3cure-pass", "new-pass-123") == 1
    assert users.authenticate("georgy", "new-pass-123") is not None


def test_delete_user_cascades_to_items():
    uid = users.create_user("georgy", "s3cure-pass")
    roadmap.create(uid, "PEH", "course", "TCM", "", "web", "beginner", 3)
    assert users.delete_user(uid) is True
    assert roadmap.get_all(uid) == []


def test_check_can_delete_needs_password_and_protects_last_admin():
    uid = users.create_user("georgy", "s3cure-pass")
    with pytest.raises(users.AccountError, match="wrong"):
        users.check_can_delete(uid, "nope")
    users.check_can_delete(uid, "s3cure-pass")   # no exception
    with db.transaction() as cur:
        cur.execute("UPDATE users SET is_admin = 1 WHERE id = %s", (uid,))
    with pytest.raises(users.AccountError, match="only admin"):
        users.check_can_delete(uid, "s3cure-pass")


def test_login_history_and_failed_since_last_login():
    uid = users.create_user("georgy", "s3cure-pass")
    users.record_login(uid, True, "1.1.1.1")
    users.record_login(uid, False, "6.6.6.6")
    users.record_login(uid, False, "6.6.6.6")
    assert users.failed_since_last_login(uid) == 2
    recent = users.recent_logins(uid, limit=2)
    assert [r["success"] for r in recent] == [False, False]
    assert len(recent) == 2


def test_set_path():
    uid = users.create_user("georgy", "s3cure-pass")
    users.set_path(uid, "pentest", "beginner")
    assert users.get_by_id(uid)["path_field"] == "pentest"

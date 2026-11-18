import os
import tempfile

import pytest

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATA_DIR"] = os.path.dirname(tmp.name)

import db
import models.assessment as assessment
import models.users as users

db.DB_PATH = tmp.name


@pytest.fixture(autouse=True)
def fresh_db():
    db.init_db()
    yield
    with db.get_db() as conn:
        conn.executescript("DELETE FROM assessments; DELETE FROM users;")


@pytest.fixture
def uid():
    return users.create_user("alice", "correct-horse")


def test_save_and_get_round_trips_answers(uid):
    attempt_id = assessment.save(uid, "soc", {"soc-1": 1, "soc-2": 0}, 3, 6, "intermediate")
    attempt = assessment.get(attempt_id, uid)
    assert attempt["answers"] == {"soc-1": 1, "soc-2": 0}
    assert (attempt["field"], attempt["score"], attempt["max_score"], attempt["level"]) == ("soc", 3, 6, "intermediate")


def test_other_users_attempt_is_not_found(uid):
    attempt_id = assessment.save(uid, "soc", {}, 0, 6, "none")
    mallory = users.create_user("mallory", "correct-horse")
    assert assessment.get(attempt_id, mallory) is None          # no IDOR
    assert assessment.get(9999, uid) is None


def test_history_is_newest_first_limited_and_per_user(uid):
    for score in (1, 2, 3):
        assessment.save(uid, "grc", {}, score, 4, "beginner")
    other = users.create_user("bob", "correct-horse")
    assessment.save(other, "grc", {}, 4, 4, "advanced")
    rows = assessment.history(uid, limit=2)
    assert [r["score"] for r in rows] == [3, 2]
    assert rows[0]["percent"] == 75


def test_attempts_are_deleted_with_the_user(uid):
    assessment.save(uid, "cloud", {}, 1, 3, "beginner")
    users.delete_user(uid)
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM assessments").fetchone()["n"] == 0

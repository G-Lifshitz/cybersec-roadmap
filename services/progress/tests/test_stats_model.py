import os
import tempfile

import pytest

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATA_DIR"] = os.path.dirname(tmp.name)

import db
import models.progress as progress
import models.roadmap as roadmap
import models.users as users

db.DB_PATH = tmp.name


@pytest.fixture(autouse=True)
def fresh_db():
    db.init_db()
    yield
    with db.get_db() as conn:
        conn.executescript("DELETE FROM progress_logs; DELETE FROM roadmap_items; DELETE FROM users;")


def test_time_entries_are_owner_scoped_with_dates_and_tags():
    alice = users.create_user("alice", "correct-horse")
    bob = users.create_user("bob", "correct-horse")
    item = roadmap.create(alice, "Alice item", "course", "THM", "", "web, linux", "beginner", 3)
    other = roadmap.create(bob, "Bob item", "lab", "HTB", "", "network", "beginner", 3)
    progress.add_log(item, 20, "fair", "", 45)
    progress.add_log(item, 40, "hard", "", None)          # no time given -> counts as 0 minutes
    progress.add_log(other, 10, "easy", "", 999)
    rows = progress.time_entries(alice)
    assert [r["minutes"] for r in rows] == [45, 0]
    assert all(r["skill_tags"] == "web,linux" for r in rows)
    assert len(rows[0]["day"]) == 10 and rows[0]["day"][4] == "-"      # 'YYYY-MM-DD'


def test_time_entries_empty_for_new_user():
    assert progress.time_entries(users.create_user("carol", "correct-horse")) == []

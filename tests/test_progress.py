import os
import tempfile
import pytest

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATA_DIR"] = os.path.dirname(tmp.name)

import db
import models.roadmap as roadmap
import models.users as users
import models.progress as progress

db.DB_PATH = tmp.name


UID = None  # id of the test user every item belongs to; set fresh for each test


@pytest.fixture(autouse=True)
def fresh_db():
    global UID
    db.init_db()
    UID = users.create_user("alice", "correct-horse")
    yield
    with db.get_db() as conn:
        conn.executescript("DELETE FROM progress_logs; DELETE FROM roadmap_items; DELETE FROM users;")


@pytest.fixture
def item_id():
    return roadmap.create(UID, "PEH", "course", "TCM", "", "web,network", "beginner", 3)


def test_add_log(item_id):
    log_id = progress.add_log(item_id, 50, "fair", "covered recon section", 90)
    assert log_id is not None
    logs = progress.get_logs_for_item(item_id)
    assert len(logs) == 1
    assert logs[0]["completion_pct"] == 50


def test_completion_at_100_marks_item_completed(item_id):
    progress.add_log(item_id, 100, "easy", "done!", 120)
    item = roadmap.get_by_id(item_id, UID)
    assert item["status"] == "completed"


def test_partial_completion_marks_in_progress(item_id):
    progress.add_log(item_id, 40, "fair", "", 60)
    item = roadmap.get_by_id(item_id, UID)
    assert item["status"] == "in_progress"


def test_latest_completion_returns_most_recent(item_id):
    progress.add_log(item_id, 30, "fair", "", 30)
    progress.add_log(item_id, 70, "hard", "", 60)
    assert progress.latest_completion(item_id) == 70


def test_latest_completion_no_logs(item_id):
    assert progress.latest_completion(item_id) == 0


def test_weak_skills_identifies_hard_areas(item_id):
    # Two hard logs on "web,network" item
    progress.add_log(item_id, 30, "hard", "", 60)
    progress.add_log(item_id, 50, "brutal", "", 60)
    weak = progress.weak_skills(UID)
    assert "web" in weak
    assert "network" in weak


def test_weak_skills_ignores_easy_skills(item_id):
    progress.add_log(item_id, 80, "easy", "", 60)
    progress.add_log(item_id, 90, "fair", "", 60)
    weak = progress.weak_skills(UID)
    assert "web" not in weak


def test_total_time_spent(item_id):
    progress.add_log(item_id, 30, "fair", "", 45)
    progress.add_log(item_id, 60, "fair", "", 90)
    assert progress.total_time_spent(UID) == 135


def test_multiple_logs_ordered_desc(item_id):
    progress.add_log(item_id, 20, "easy", "first", 20)
    progress.add_log(item_id, 50, "hard", "second", 40)
    logs = progress.get_logs_for_item(item_id)
    # Most recent first
    assert logs[0]["notes"] == "second"


def test_weak_skills_and_time_are_per_user(item_id):
    # Alice struggles with web; Bob has no logs at all
    progress.add_log(item_id, 30, "brutal", "", 60)
    bob = users.create_user("bob", "another-pass")
    assert progress.weak_skills(bob) == []
    assert progress.total_time_spent(bob) == 0
    assert progress.total_time_spent(UID) == 60

import os
import tempfile
import pytest

# Point DB at a temp file before importing app modules
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATA_DIR"] = os.path.dirname(tmp.name)

import db
import models.roadmap as roadmap

# Override DB_PATH to use temp file
db.DB_PATH = tmp.name


@pytest.fixture(autouse=True)
def fresh_db():
    db.init_db()
    yield
    # Wipe tables between tests
    with db.get_db() as conn:
        conn.executescript("DELETE FROM progress_logs; DELETE FROM roadmap_items;")


def test_create_item():
    item_id = roadmap.create("PEH Course", "course", "TCM", "https://tcm.com",
                             "web,network", "beginner", 4)
    assert item_id is not None
    item = roadmap.get_by_id(item_id)
    assert item["title"] == "PEH Course"
    assert item["status"] == "not_started"


def test_get_all_returns_all():
    roadmap.create("Item A", "course", "THM", "", "web", "beginner", 3)
    roadmap.create("Item B", "lab", "HTB", "", "network", "intermediate", 5)
    items = roadmap.get_all()
    assert len(items) == 2


def test_get_all_filter_by_status():
    roadmap.create("Item A", "course", "THM", "", "web", "beginner", 3)
    id2 = roadmap.create("Item B", "lab", "HTB", "", "network", "intermediate", 5)
    roadmap.update_status(id2, "completed")
    completed = roadmap.get_all(status="completed")
    assert len(completed) == 1
    assert completed[0]["id"] == id2


def test_update_status():
    item_id = roadmap.create("OSCP", "cert", "OffSec", "", "pentest", "advanced", 5)
    roadmap.update_status(item_id, "in_progress")
    item = roadmap.get_by_id(item_id)
    assert item["status"] == "in_progress"


def test_delete_item():
    item_id = roadmap.create("Temp", "course", "THM", "", "web", "beginner", 1)
    roadmap.delete(item_id)
    assert roadmap.get_by_id(item_id) is None


def test_skill_summary():
    roadmap.create("A", "course", "THM", "", "web,network", "beginner", 3)
    roadmap.create("B", "lab", "HTB", "", "web", "intermediate", 3)
    summary = roadmap.get_skill_summary()
    assert "web" in summary
    assert summary["web"]["not_started"] == 2
    assert "network" in summary


def test_get_by_id_nonexistent():
    assert roadmap.get_by_id(9999) is None

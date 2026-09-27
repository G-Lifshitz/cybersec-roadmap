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


# ── Edit ────────────────────────────────────────────────────────────────────

def test_update_changes_editable_fields():
    item_id = roadmap.create("Old title", "course", "THM", "", "web", "beginner", 2)
    changed = roadmap.update(item_id, title="New title", priority=5, difficulty="advanced")
    assert changed is True
    item = roadmap.get_by_id(item_id)
    assert item["title"] == "New title"
    assert item["priority"] == 5
    assert item["difficulty"] == "advanced"
    assert item["platform"] == "THM"  # untouched fields keep their value


def test_update_ignores_non_editable_fields():
    item_id = roadmap.create("Item", "course", "", "", "", "beginner", 3)
    # status and id are not in EDITABLE_FIELDS, so nothing should change
    assert roadmap.update(item_id, status="completed", id=999) is False
    item = roadmap.get_by_id(item_id)
    assert item["status"] == "not_started"
    assert item["id"] == item_id


def test_update_nonexistent_item_returns_false():
    assert roadmap.update(99999, title="Ghost") is False


def test_update_normalises_tags():
    item_id = roadmap.create("Item", "course", "", "", "web", "beginner", 3)
    roadmap.update(item_id, skill_tags=" Web , NETWORK,, web ")
    assert roadmap.get_by_id(item_id)["skill_tags"] == "web,network"


# ── Filtering ───────────────────────────────────────────────────────────────

def test_filter_by_tag_is_exact_match():
    roadmap.create("Web basics", "course", "", "", "web", "beginner", 3)
    roadmap.create("Web3 intro", "course", "", "", "web3", "beginner", 3)
    titles = [r["title"] for r in roadmap.get_all(skill="web")]
    assert titles == ["Web basics"]  # "web" must not match "web3"


def test_filter_by_search_matches_title_and_platform():
    roadmap.create("Jr Pentester path", "course", "THM", "", "", "beginner", 3)
    roadmap.create("Dante Pro Lab", "lab", "HTB", "", "", "advanced", 3)
    assert len(roadmap.get_all(search="pentester")) == 1
    assert len(roadmap.get_all(search="htb")) == 1
    assert len(roadmap.get_all(search="nothing-matches")) == 0


def test_filter_by_type_and_status_combined():
    a = roadmap.create("OSCP", "cert", "OffSec", "", "", "advanced", 5)
    roadmap.create("Security+", "cert", "", "", "", "beginner", 3)
    roadmap.create("PEH", "course", "TCM", "", "", "beginner", 4)
    roadmap.update_status(a, "in_progress")
    results = roadmap.get_all(type_="cert", status="in_progress")
    assert [r["title"] for r in results] == ["OSCP"]


# ── Helpers ─────────────────────────────────────────────────────────────────

def test_get_all_tags_sorted_and_unique():
    roadmap.create("A", "course", "", "", "web,network", "beginner", 3)
    roadmap.create("B", "course", "", "", "Network, crypto", "beginner", 3)
    assert roadmap.get_all_tags() == ["crypto", "network", "web"]


def test_status_counts():
    a = roadmap.create("A", "course", "", "", "", "beginner", 3)
    roadmap.create("B", "course", "", "", "", "beginner", 3)
    roadmap.update_status(a, "completed")
    counts = roadmap.get_status_counts()
    assert counts == {"not_started": 1, "in_progress": 0, "completed": 1, "total": 2}

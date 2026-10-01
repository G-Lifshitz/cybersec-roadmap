import os
import tempfile
import pytest

# Point DB at a temp file before importing app modules
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATA_DIR"] = os.path.dirname(tmp.name)

import db
import models.roadmap as roadmap
import models.users as users

# Override DB_PATH to use temp file
db.DB_PATH = tmp.name


UID = None  # id of the test user every item belongs to; set fresh for each test


@pytest.fixture(autouse=True)
def fresh_db():
    global UID
    db.init_db()
    UID = users.create_user("alice", "correct-horse")
    yield
    # Wipe tables between tests
    with db.get_db() as conn:
        conn.executescript("DELETE FROM progress_logs; DELETE FROM roadmap_items; DELETE FROM users;")


def test_create_item():
    item_id = roadmap.create(UID, "PEH Course", "course", "TCM", "https://tcm.com",
                             "web,network", "beginner", 4)
    assert item_id is not None
    item = roadmap.get_by_id(item_id, UID)
    assert item["title"] == "PEH Course"
    assert item["status"] == "not_started"


def test_get_all_returns_all():
    roadmap.create(UID, "Item A", "course", "THM", "", "web", "beginner", 3)
    roadmap.create(UID, "Item B", "lab", "HTB", "", "network", "intermediate", 5)
    items = roadmap.get_all(UID)
    assert len(items) == 2


def test_get_all_filter_by_status():
    roadmap.create(UID, "Item A", "course", "THM", "", "web", "beginner", 3)
    id2 = roadmap.create(UID, "Item B", "lab", "HTB", "", "network", "intermediate", 5)
    roadmap.update_status(id2, UID, "completed")
    completed = roadmap.get_all(UID, status="completed")
    assert len(completed) == 1
    assert completed[0]["id"] == id2


def test_update_status():
    item_id = roadmap.create(UID, "OSCP", "cert", "OffSec", "", "pentest", "advanced", 5)
    roadmap.update_status(item_id, UID, "in_progress")
    item = roadmap.get_by_id(item_id, UID)
    assert item["status"] == "in_progress"


def test_delete_item():
    item_id = roadmap.create(UID, "Temp", "course", "THM", "", "web", "beginner", 1)
    roadmap.delete(item_id, UID)
    assert roadmap.get_by_id(item_id, UID) is None


def test_skill_summary():
    roadmap.create(UID, "A", "course", "THM", "", "web,network", "beginner", 3)
    roadmap.create(UID, "B", "lab", "HTB", "", "web", "intermediate", 3)
    summary = roadmap.get_skill_summary(UID)
    assert "web" in summary
    assert summary["web"]["not_started"] == 2
    assert "network" in summary


def test_get_by_id_nonexistent():
    assert roadmap.get_by_id(9999, UID) is None


# ── Edit ────────────────────────────────────────────────────────────────────

def test_update_changes_editable_fields():
    item_id = roadmap.create(UID, "Old title", "course", "THM", "", "web", "beginner", 2)
    changed = roadmap.update(item_id, UID, title="New title", priority=5, difficulty="advanced")
    assert changed is True
    item = roadmap.get_by_id(item_id, UID)
    assert item["title"] == "New title"
    assert item["priority"] == 5
    assert item["difficulty"] == "advanced"
    assert item["platform"] == "THM"  # untouched fields keep their value


def test_update_ignores_non_editable_fields():
    item_id = roadmap.create(UID, "Item", "course", "", "", "", "beginner", 3)
    # status and id are not in EDITABLE_FIELDS, so nothing should change
    assert roadmap.update(item_id, UID, status="completed", id=999) is False
    item = roadmap.get_by_id(item_id, UID)
    assert item["status"] == "not_started"
    assert item["id"] == item_id


def test_update_nonexistent_item_returns_false():
    assert roadmap.update(99999, UID, title="Ghost") is False


def test_update_normalises_tags():
    item_id = roadmap.create(UID, "Item", "course", "", "", "web", "beginner", 3)
    roadmap.update(item_id, UID, skill_tags=" Web , NETWORK,, web ")
    assert roadmap.get_by_id(item_id, UID)["skill_tags"] == "web,network"


# ── Filtering ───────────────────────────────────────────────────────────────

def test_filter_by_tag_is_exact_match():
    roadmap.create(UID, "Web basics", "course", "", "", "web", "beginner", 3)
    roadmap.create(UID, "Web3 intro", "course", "", "", "web3", "beginner", 3)
    titles = [r["title"] for r in roadmap.get_all(UID, skill="web")]
    assert titles == ["Web basics"]  # "web" must not match "web3"


def test_filter_by_search_matches_title_and_platform():
    roadmap.create(UID, "Jr Pentester path", "course", "THM", "", "", "beginner", 3)
    roadmap.create(UID, "Dante Pro Lab", "lab", "HTB", "", "", "advanced", 3)
    assert len(roadmap.get_all(UID, search="pentester")) == 1
    assert len(roadmap.get_all(UID, search="htb")) == 1
    assert len(roadmap.get_all(UID, search="nothing-matches")) == 0


def test_filter_by_type_and_status_combined():
    a = roadmap.create(UID, "OSCP", "cert", "OffSec", "", "", "advanced", 5)
    roadmap.create(UID, "Security+", "cert", "", "", "", "beginner", 3)
    roadmap.create(UID, "PEH", "course", "TCM", "", "", "beginner", 4)
    roadmap.update_status(a, UID, "in_progress")
    results = roadmap.get_all(UID, type_="cert", status="in_progress")
    assert [r["title"] for r in results] == ["OSCP"]


# ── Helpers ─────────────────────────────────────────────────────────────────

def test_get_all_tags_sorted_and_unique():
    roadmap.create(UID, "A", "course", "", "", "web,network", "beginner", 3)
    roadmap.create(UID, "B", "course", "", "", "Network, crypto", "beginner", 3)
    assert roadmap.get_all_tags(UID) == ["crypto", "network", "web"]


def test_status_counts():
    a = roadmap.create(UID, "A", "course", "", "", "", "beginner", 3)
    roadmap.create(UID, "B", "course", "", "", "", "beginner", 3)
    roadmap.update_status(a, UID, "completed")
    counts = roadmap.get_status_counts(UID)
    assert counts == {"not_started": 1, "in_progress": 0, "completed": 1, "total": 2}


# ── Ownership: one user must never see or touch another user's items ────────

def test_items_are_private_to_their_owner():
    bob = users.create_user("bob", "another-pass")
    alice_item = roadmap.create(UID, "Alice's cert", "cert", "", "", "web", "beginner", 3)
    roadmap.create(bob, "Bob's lab", "lab", "", "", "network", "beginner", 3)

    assert [r["title"] for r in roadmap.get_all(UID)] == ["Alice's cert"]
    assert [r["title"] for r in roadmap.get_all(bob)] == ["Bob's lab"]
    assert roadmap.get_all_tags(bob) == ["network"]
    assert roadmap.get_status_counts(bob)["total"] == 1
    # Bob guessing Alice's item id gets nothing back
    assert roadmap.get_by_id(alice_item, bob) is None


def test_cannot_edit_or_delete_someone_elses_item():
    bob = users.create_user("bob", "another-pass")
    item_id = roadmap.create(UID, "Alice's cert", "cert", "", "", "", "beginner", 3)

    assert roadmap.update(item_id, bob, title="hacked") is False
    assert roadmap.delete(item_id, bob) is False
    assert roadmap.get_by_id(item_id, UID)["title"] == "Alice's cert"


# ── SQL injection: payloads must be stored and matched as plain text ────────

INJECTIONS = [
    "'; DROP TABLE roadmap_items; --",
    "' OR '1'='1",
    "\" OR 1=1 --",
    "x'); DELETE FROM users; --",
]


@pytest.mark.parametrize("payload", INJECTIONS)
def test_injection_in_fields_is_stored_literally(payload):
    item_id = roadmap.create(UID, payload, "course", payload, "", payload, "beginner", 3)
    item = roadmap.get_by_id(item_id, UID)
    assert item["title"] == payload          # saved exactly as typed
    assert len(roadmap.get_all(UID)) == 1    # table still exists, nothing dropped


@pytest.mark.parametrize("payload", INJECTIONS)
def test_injection_in_filters_matches_nothing_extra(payload):
    bob = users.create_user("bob", "another-pass")
    roadmap.create(bob, "Bob's private item", "course", "", "", "web", "beginner", 3)
    roadmap.create(UID, "Alice item", "course", "", "", "web", "beginner", 3)
    # A classic "' OR '1'='1" must not widen the query to other users' rows
    assert roadmap.get_all(UID, search=payload) == []
    assert roadmap.get_all(UID, status=payload) == []
    assert roadmap.get_all(UID, skill=payload) == []
    assert roadmap.get_all(UID, type_=payload) == []


def test_update_cannot_inject_through_column_names():
    item_id = roadmap.create(UID, "Item", "course", "", "", "", "beginner", 3)
    # Keys aren't in EDITABLE_FIELDS, so they never reach the SQL string
    assert roadmap.update(item_id, UID, **{"title = 'x', user_id": 999}) is False
    assert roadmap.get_by_id(item_id, UID)["title"] == "Item"


def test_split_tags_trims_lowercases_and_drops_empties():
    assert roadmap.split_tags(" Web, NETWORK ,, ") == ["web", "network"]
    assert roadmap.split_tags(None) == []


def _rows(*titles):
    return [{"title": t, "type": "course", "platform": "Other", "url": "",
             "skill_tags": "Web, web", "difficulty": "beginner", "priority": 4} for t in titles]


def test_create_many_adds_items_and_normalises_tags():
    assert roadmap.create_many(UID, _rows("First", "Second")) == 2
    items = roadmap.get_all(UID)
    assert {i["title"] for i in items} == {"First", "Second"}
    assert items[0]["skill_tags"] == "web"


def test_create_many_skips_titles_the_user_already_has():
    roadmap.create(UID, "First", "course", "Other", "", "", "beginner", 3)
    assert roadmap.create_many(UID, _rows(" first ", "Second", "SECOND")) == 1
    assert len(roadmap.get_all(UID)) == 2


def test_create_many_ignores_other_users_titles():
    bob = users.create_user("bob_b", "correct-horse")
    roadmap.create(bob, "First", "course", "Other", "", "", "beginner", 3)
    assert roadmap.create_many(UID, _rows("First")) == 1

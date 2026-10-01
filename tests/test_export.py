import csv
import io
import json
import os
import tempfile

import pytest

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATA_DIR"] = os.path.dirname(tmp.name)

import db
import models.assessment as assessment
import models.progress as progress
import models.roadmap as roadmap
import models.users as users
import services.export as export

db.DB_PATH = tmp.name


@pytest.fixture(autouse=True)
def fresh_db():
    db.init_db()
    yield
    with db.get_db() as conn:
        conn.executescript("DELETE FROM progress_logs; DELETE FROM roadmap_items; DELETE FROM assessments; DELETE FROM users;")


@pytest.fixture
def alice():
    uid = users.create_user("alice", "correct-horse")
    item = roadmap.create(uid, "Alice item", "course", "THM", "", "web", "beginner", 3)
    progress.add_log(item, 50, "fair", "halfway", 60)
    assessment.save(uid, "soc", {"soc-1": 1}, 3, 21, "beginner")
    users.record_login(uid, True, "10.0.0.1")
    return uid


def test_export_contains_every_table_for_the_user(alice):
    data = export.collect(alice)
    assert data["account"]["username"] == "alice"
    assert [i["title"] for i in data["roadmap_items"]] == ["Alice item"]
    assert data["progress_logs"][0]["item_title"] == "Alice item"
    assert data["assessments"][0]["answers"] == {"soc-1": 1}
    assert data["login_events"][0]["ip"] == "10.0.0.1"


def test_export_never_contains_secrets_or_other_users_data(alice):
    bob = users.create_user("bob", "correct-horse")
    other = roadmap.create(bob, "Bob secret item", "lab", "HTB", "", "", "beginner", 3)
    progress.add_log(other, 10, "hard", "bob's notes", 30)
    dumped = export.to_json(export.collect(alice))
    assert "Bob secret item" not in dumped and "bob's notes" not in dumped
    assert "password_hash" not in dumped and "session_epoch" not in dumped
    assert "scrypt" not in dumped and "pbkdf2" not in dumped


def test_json_round_trips(alice):
    assert json.loads(export.to_json(export.collect(alice)))["account"]["username"] == "alice"


def test_items_csv_has_header_and_rows(alice):
    body, content_type = export.FORMATS["items.csv"]
    rows = list(csv.reader(io.StringIO(body(export.collect(alice)))))
    assert content_type == "text/csv"
    assert rows[0] == list(export.ITEM_COLUMNS) and rows[1][1] == "Alice item"


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tx"])
def test_formula_like_text_is_neutralised(value):
    assert export.safe_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["plain", "", 42, -5, None])
def test_normal_values_are_unchanged(value):
    assert export.safe_cell(value) == value


def test_csv_injection_in_a_real_export():
    uid = users.create_user("carol", "correct-horse")
    roadmap.create(uid, '=HYPERLINK("http://evil.example","click")', "book", "Other", "", "", "beginner", 1)
    body = export.FORMATS["items.csv"][0](export.collect(uid))
    assert "'=HYPERLINK" in body


def test_every_format_builds(alice):
    data = export.collect(alice)
    for name, (build, content_type) in export.FORMATS.items():
        assert build(data) and content_type in ("application/json", "text/csv")

"""Roadmap HTTP API with the models replaced by small fakes: no database needed.

These cover what the routes add on top of the models: token checks, input
validation, owner scoping, and the calls across the seam to progress.
"""
import logging

import pytest

import app as roadmap_app
import auth
import db
from progress_client import ProgressUnavailable

USER = {"id": 7, "username": "georgy", "is_admin": False, "session_epoch": 0,
        "path_field": None, "path_level": None}
ITEM = {"id": 1, "user_id": 7, "title": "PEH", "type": "course", "platform": "TCM", "url": "",
        "skill_tags": "web", "difficulty": "beginner", "priority": 3, "status": "not_started",
        "created_at": "2026-11-18T10:00:00"}


class FakeProgress:
    def __init__(self, down=False):
        self.down, self.calls = down, []

    def delete_item_logs(self, token, item_id):
        self.calls.append(("item", item_id))
        if self.down:
            raise ProgressUnavailable("down")
        return 2

    def delete_user_logs(self, token):
        self.calls.append(("user",))
        if self.down:
            raise ProgressUnavailable("down")
        return 5


@pytest.fixture
def models(monkeypatch):
    """Patch the model functions the routes use; returns a dict of recorded calls."""
    calls = {"deleted_user": False}
    m = roadmap_app
    monkeypatch.setattr(m.users_model, "get_by_id", lambda uid: dict(USER) if uid == 7 else None)
    monkeypatch.setattr(m.roadmap_model, "get_by_id", lambda iid, uid: dict(ITEM) if (iid, uid) == (1, 7) else None)
    monkeypatch.setattr(m.roadmap_model, "get_all", lambda uid, **kw: [dict(ITEM)])
    monkeypatch.setattr(m.roadmap_model, "delete", lambda iid, uid: (iid, uid) == (1, 7))
    monkeypatch.setattr(m.roadmap_model, "update_status", lambda iid, uid, s: (iid, uid) == (1, 7))
    monkeypatch.setattr(m.roadmap_model, "create", lambda *a: 1)
    monkeypatch.setattr(m.users_model, "check_can_delete", lambda uid, pw: None)
    monkeypatch.setattr(m.users_model, "delete_user",
                        lambda uid: calls.__setitem__("deleted_user", True))
    monkeypatch.setattr(m.assessment_model, "history", lambda uid, limit=10: [])
    return calls


def client_for(progress=None):
    return roadmap_app.create_app(progress=progress or FakeProgress()).test_client()


def auth_header(uid=7, epoch=0):
    return {"Authorization": f"Bearer {auth.issue(uid, epoch)}"}


def test_items_need_a_token(models):
    c = client_for()
    assert c.get("/items").status_code == 401
    assert c.get("/items", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_token_from_before_a_password_change_is_rejected(models):
    c = client_for()
    assert c.get("/items", headers=auth_header(epoch=0)).status_code == 200
    assert c.get("/items", headers=auth_header(epoch=-1)).status_code == 401


def test_other_users_item_is_404(models):
    c = client_for()
    assert c.get("/items/1", headers=auth_header()).get_json()["item"]["title"] == "PEH"
    assert c.get("/items/2", headers=auth_header()).status_code == 404


def test_create_item_validates_input(models):
    c = client_for()
    h = auth_header()
    assert c.post("/items", json={"title": ""}, headers=h).status_code == 400
    assert c.post("/items", json={"title": "x", "url": "javascript:alert(1)"}, headers=h).status_code == 400
    assert c.post("/items", data="not json", headers=h).status_code == 400
    assert c.post("/items", json={"title": "Linux 101", "type": "evil"}, headers=h).status_code == 201


def test_set_status_rejects_unknown_status(models):
    c = client_for()
    h = auth_header()
    assert c.patch("/items/1/status", json={"status": "hacked"}, headers=h).status_code == 400
    assert c.patch("/items/1/status", json={"status": "completed"}, headers=h).status_code == 200


def test_delete_item_also_deletes_its_logs_in_progress(models):
    progress = FakeProgress()
    resp = client_for(progress).delete("/items/1", headers=auth_header())
    assert resp.get_json() == {"deleted": True, "logs_deleted": 2}
    assert progress.calls == [("item", 1)]


def test_delete_item_still_works_when_progress_is_down(models):
    resp = client_for(FakeProgress(down=True)).delete("/items/1", headers=auth_header())
    assert resp.status_code == 200
    assert resp.get_json()["logs_deleted"] is None


def test_account_deletion_is_refused_when_progress_is_down(models):
    resp = client_for(FakeProgress(down=True)).delete("/me", json={"password": "x"}, headers=auth_header())
    assert resp.status_code == 503
    assert "kept" in resp.get_json()["message"]
    assert models["deleted_user"] is False


def test_account_deletion_removes_logs_first(models):
    progress = FakeProgress()
    resp = client_for(progress).delete("/me", json={"password": "x"}, headers=auth_header())
    assert resp.status_code == 204
    assert progress.calls == [("user",)] and models["deleted_user"] is True


def test_questions_do_not_leak_the_points(models):
    c = client_for()
    field = c.get("/assessments", headers=auth_header()).get_json()["fields"][0]["key"]
    body = c.get(f"/assessments/{field}", headers=auth_header()).get_data(as_text=True)
    assert "points" not in body


def test_health_ok_and_unavailable(monkeypatch):
    c = client_for()
    monkeypatch.setattr(db, "check", lambda: True)
    resp = c.get("/health")
    assert resp.status_code == 200 and resp.get_json()["db"] == "ok"

    def broken():
        raise db.DatabaseUnavailable("paused")
    monkeypatch.setattr(db, "check", broken)
    resp = c.get("/health")
    assert resp.status_code == 503 and resp.get_json()["status"] == "error"


def test_database_still_resuming_is_a_designed_503(models, monkeypatch):
    def paused(uid, **kw):
        raise db.DatabaseUnavailable("40613")
    monkeypatch.setattr(roadmap_app.roadmap_model, "get_all", paused)
    resp = client_for().get("/items", headers=auth_header())
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "starting_up"
    assert resp.headers["Retry-After"] == "30"


def test_every_request_is_logged(models, caplog):
    with caplog.at_level(logging.INFO, logger="http"):
        client_for().get("/items/1", headers=auth_header())
    line = next(r.getMessage() for r in caplog.records if r.name == "http")
    assert line.startswith("GET /items/1 200 ") and line.endswith("ms")


def test_cors_allows_only_the_ui_origin(models, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://ui.example")
    c = client_for()
    ok = c.options("/items", headers={"Origin": "https://ui.example", "Access-Control-Request-Method": "POST",
                                      "Access-Control-Request-Headers": "content-type,authorization"})
    assert ok.headers.get("Access-Control-Allow-Origin") == "https://ui.example"
    bad = c.get("/options", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in bad.headers


def test_unknown_route_is_json_404():
    resp = client_for().get("/nope")
    assert resp.status_code == 404 and resp.get_json()["error"] == "not_found"

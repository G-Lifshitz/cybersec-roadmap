"""Progress HTTP API with the model faked and the roadmap service stubbed.

The stub is the "other service replaced by a stub" option of A2 §5; the
compose-stack integration test (tests/integration) exercises the real one.
"""
import pytest

import app as progress_app
import auth
import db
from roadmap_client import RoadmapUnavailable

ITEM = {"id": 10, "title": "PEH", "status": "not_started", "skill_tags": "web,linux"}


class StubRoadmap:
    def __init__(self, down=False, status_fails=False):
        self.down, self.status_fails, self.status_calls = down, status_fails, []

    def _check(self):
        if self.down:
            raise RoadmapUnavailable("connection refused")

    def get_item(self, token, item_id):
        self._check()
        return dict(ITEM) if item_id == 10 else None

    def set_status(self, token, item_id, status):
        if self.status_fails:
            raise RoadmapUnavailable("timeout")
        self.status_calls.append((item_id, status))

    def tags_by_item(self, token):
        self._check()
        return {10: "web,linux", 11: "network"}


@pytest.fixture
def store(monkeypatch):
    """An in-memory stand-in for models.progress."""
    logs = []
    m = progress_app.progress_model

    def add_log(uid, item_id, pct, felt, notes, mins):
        logs.append({"id": len(logs) + 1, "user_id": uid, "item_id": item_id, "completion_pct": pct,
                     "felt_difficulty": felt, "notes": notes, "minutes": mins or 0,
                     "day": "2026-11-18"})
        return len(logs)

    monkeypatch.setattr(m, "add_log", add_log)
    monkeypatch.setattr(m, "get_logs_for_item",
                        lambda uid, iid: [x for x in reversed(logs) if (x["user_id"], x["item_id"]) == (uid, iid)])
    monkeypatch.setattr(m, "time_entries", lambda uid: [x for x in logs if x["user_id"] == uid])
    monkeypatch.setattr(m, "rated_logs", lambda uid: [x for x in logs if x["user_id"] == uid and x["felt_difficulty"]])
    monkeypatch.setattr(m, "latest_completion_by_item",
                        lambda uid: {x["item_id"]: x["completion_pct"] for x in logs if x["user_id"] == uid})
    monkeypatch.setattr(m, "delete_for_user", lambda uid: len(logs))
    return logs


def client(roadmap=None):
    return progress_app.create_app(roadmap=roadmap or StubRoadmap()).test_client()


H = None


@pytest.fixture(autouse=True)
def headers():
    global H
    H = {"Authorization": f"Bearer {auth.issue(7, 0)}"}


def test_needs_a_valid_token(store):
    assert client().get("/items/10/logs").status_code == 401
    assert client().get("/items/10/logs", headers={"Authorization": "Bearer x"}).status_code == 401


def test_logging_progress_checks_the_item_and_syncs_status(store):
    roadmap = StubRoadmap()
    resp = client(roadmap).post("/items/10/logs", json={"completion_pct": 100, "time_spent_mins": 30}, headers=H)
    assert resp.status_code == 201
    assert resp.get_json() == {"id": 1, "item_status": "completed", "status_synced": True}
    assert roadmap.status_calls == [(10, "completed")]
    assert store[0]["user_id"] == 7


def test_logging_on_someone_elses_or_missing_item_is_404(store):
    resp = client().post("/items/99/logs", json={"completion_pct": 10}, headers=H)
    assert resp.status_code == 404 and store == []


def test_logging_with_roadmap_down_fails_cleanly_and_saves_nothing(store):
    resp = client(StubRoadmap(down=True)).post("/items/10/logs", json={"completion_pct": 10}, headers=H)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "roadmap_unavailable"
    assert resp.headers["Retry-After"] == "30"
    assert store == []


def test_log_is_kept_when_only_the_status_sync_fails(store):
    resp = client(StubRoadmap(status_fails=True)).post("/items/10/logs", json={"completion_pct": 50}, headers=H)
    assert resp.status_code == 201 and resp.get_json()["status_synced"] is False
    assert len(store) == 1


def test_zero_percent_log_does_not_touch_the_status(store):
    roadmap = StubRoadmap()
    client(roadmap).post("/items/10/logs", json={"completion_pct": 0}, headers=H)
    assert roadmap.status_calls == []


@pytest.mark.parametrize("payload", [{"completion_pct": "lots"}, {"time_spent_mins": "x"}])
def test_bad_numbers_are_400(store, payload):
    assert client().post("/items/10/logs", json=payload, headers=H).status_code == 400


def test_input_is_clamped_and_unknown_difficulty_dropped(store):
    client().post("/items/10/logs", json={"completion_pct": 400, "time_spent_mins": 99999,
                                          "felt_difficulty": "insane", "notes": "n" * 5000}, headers=H)
    log = store[0]
    assert (log["completion_pct"], log["minutes"], log["felt_difficulty"]) == (100, 1440, None)
    assert len(log["notes"]) == 2000


def test_reading_logs_works_with_roadmap_down(store):
    client().post("/items/10/logs", json={"completion_pct": 40}, headers=H)
    resp = client(StubRoadmap(down=True)).get("/items/10/logs", headers=H)
    assert resp.status_code == 200 and resp.get_json()["completion"] == 40


def test_summary_full_and_degraded(store):
    for pct, felt in ((20, "hard"), (40, "brutal"), (60, "fair")):
        client().post("/items/10/logs", json={"completion_pct": pct, "felt_difficulty": felt,
                                              "time_spent_mins": 30}, headers=H)
    full = client().get("/summary", headers=H).get_json()
    assert full["weak_skills"] == ["linux", "web"] and full["total_minutes"] == 90
    assert full["roadmap_available"] is True

    degraded = client(StubRoadmap(down=True)).get("/summary", headers=H).get_json()
    assert degraded["weak_skills"] is None and degraded["roadmap_available"] is False
    assert degraded["total_minutes"] == 90


def test_summary_ignores_logs_of_deleted_items(store):
    store.append({"id": 99, "user_id": 7, "item_id": 555, "completion_pct": 10, "felt_difficulty": None,
                  "notes": "", "minutes": 500, "day": "2026-11-18"})
    assert client().get("/summary", headers=H).get_json()["total_minutes"] == 0


def test_stats_full_and_degraded(store):
    client().post("/items/10/logs", json={"completion_pct": 10, "time_spent_mins": 45}, headers=H)
    full = client().get("/stats", headers=H).get_json()
    assert full["report"]["total_minutes"] == 45
    assert full["report"]["skills"][0][0] in ("web", "linux")
    degraded = client(StubRoadmap(down=True)).get("/stats", headers=H).get_json()
    assert degraded["report"]["skills"] is None and degraded["report"]["total_minutes"] == 45


def test_delete_all_logs(store):
    assert client().delete("/logs", headers=H).get_json() == {"deleted": 0}


def test_health_reports_own_database_only(monkeypatch):
    monkeypatch.setattr(db, "check", lambda: True)
    # Roadmap being down must not make progress unhealthy.
    resp = client(StubRoadmap(down=True)).get("/health")
    assert resp.status_code == 200 and resp.get_json()["status"] == "ok"

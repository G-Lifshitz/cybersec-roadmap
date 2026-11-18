"""The Python joins that replaced Assignment 1's cross-domain SQL JOINs, plus the roadmap client."""
import pytest
import requests

from domain import insights
from roadmap_client import RoadmapClient, RoadmapUnavailable


@pytest.mark.parametrize("pct,status", [(0, None), (1, "in_progress"), (99, "in_progress"), (100, "completed")])
def test_status_for_completion(pct, status):
    assert insights.status_for_completion(pct) == status


def test_weak_skills_needs_more_than_half_hard():
    logs = [{"item_id": 1, "felt_difficulty": "hard"}, {"item_id": 1, "felt_difficulty": "brutal"},
            {"item_id": 2, "felt_difficulty": "hard"}, {"item_id": 2, "felt_difficulty": "easy"},
            {"item_id": 3, "felt_difficulty": "hard"}]   # item 3 was deleted from the roadmap
    tags = {1: "web, Linux", 2: "network"}
    assert insights.weak_skills(logs, tags) == ["linux", "web"]


def test_with_tags_and_without_roadmap():
    entries = [{"item_id": 1, "day": "2026-11-18", "minutes": 30}]
    assert insights.with_tags(entries, {1: "web"})[0]["skill_tags"] == "web"
    assert insights.with_tags(entries, None)[0]["skill_tags"] == ""


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, *results):
        self.results, self.seen = list(results), []

    def request(self, method, url, timeout, headers, **kw):
        self.seen.append((method, url, timeout, headers["Authorization"], kw.get("json")))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_client_forwards_token_with_timeout():
    s = FakeSession(FakeResponse(200, {"item": {"id": 4}}), FakeResponse(200), FakeResponse(200, {"items": [
        {"id": 4, "skill_tags": "web"}, {"id": 5, "skill_tags": None}]}))
    c = RoadmapClient("http://roadmap:8000", timeout_s=2, session=s)
    assert c.get_item("tok", 4) == {"id": 4}
    c.set_status("tok", 4, "completed")
    assert c.tags_by_item("tok") == {4: "web", 5: ""}
    assert s.seen[0] == ("GET", "http://roadmap:8000/items/4", 2.0, "Bearer tok", None)
    assert s.seen[1][4] == {"status": "completed"}


def test_client_404_is_none_and_401_is_permission_error():
    c = RoadmapClient("http://r", timeout_s=1, session=FakeSession(FakeResponse(404), FakeResponse(401)))
    assert c.get_item("tok", 1) is None
    with pytest.raises(PermissionError):
        c.get_item("tok", 1)


@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError(), FakeResponse(503)])
def test_client_failures_become_unavailable(failure):
    c = RoadmapClient("http://r", timeout_s=1, session=FakeSession(failure))
    with pytest.raises(RoadmapUnavailable):
        c.tags_by_item("tok")

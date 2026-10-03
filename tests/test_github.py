"""Tests for services/github.py. No network: the HTTP call and the clock are fakes."""
from datetime import datetime, timezone

import pytest
import requests

import services.github as gh
from services.github import GitHubService, build_profile, parse_username, valid_username

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def repo(name, pushed="2026-10-01T10:00:00Z", **extra):
    data = {"name": name, "html_url": f"https://github.com/alice/{name}", "description": f"{name} desc",
            "language": "Python", "stargazers_count": 2, "fork": False, "pushed_at": pushed}
    data.update(extra)
    return data


def push(created_at, kind="PushEvent"):
    return {"type": kind, "created_at": created_at}


# ── Usernames ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["alice", "a", "G-Lifshitz", "user123", "a" * 39])
def test_valid_usernames(name):
    assert valid_username(name)


@pytest.mark.parametrize("name", [
    "", None, "-alice", "alice-", "al--ice", "a" * 40, "alice/repos", "../admin",
    "alice?x=1", "alice bob", "alïce", "alice.", "%2e%2e", "alice\n", 42,
])
def test_invalid_usernames(name):
    assert not valid_username(name)


@pytest.mark.parametrize("raw, expected", [
    ("alice", "alice"),
    ("  alice  ", "alice"),
    ("@alice", "alice"),
    ("https://github.com/alice", "alice"),
    ("https://github.com/alice/", "alice"),
    ("http://github.com/alice", "alice"),
    ("github.com/alice", "alice"),
    ("https://www.github.com/alice", "alice"),
    ("HTTPS://GitHub.com/Alice", "Alice"),
])
def test_parse_username_accepts_common_forms(raw, expected):
    assert parse_username(raw) == expected


@pytest.mark.parametrize("raw", [
    "", None, "https://github.com/alice/repo", "https://evil.com/alice",
    "https://github.com/", "@", "alice bob",
])
def test_parse_username_rejects_everything_else(raw):
    assert parse_username(raw) is None


# ── Building a profile from API responses ────────────────────────────────────

def test_repos_sorted_by_last_push_newest_first():
    profile = build_profile("alice", [
        repo("old", "2025-01-01T00:00:00Z"),
        repo("new", "2026-10-02T00:00:00Z"),
        repo("never", None),
        repo("mid", "2026-05-01T00:00:00Z"),
    ], [], NOW)
    assert [r.name for r in profile.repos] == ["new", "mid", "old", "never"]


def test_only_the_most_recent_repos_are_kept():
    repos = [repo(f"r{i}", f"2026-09-{i + 1:02d}T00:00:00Z") for i in range(12)]
    profile = build_profile("alice", repos, [], NOW)
    assert len(profile.repos) == gh.REPOS_SHOWN
    assert profile.repos[0].name == "r11"


def test_repo_fields_are_mapped():
    r = build_profile("alice", [repo("lab", stargazers_count=5, fork=True)], [], NOW).repos[0]
    assert (r.name, r.description, r.language, r.stars, r.fork) == ("lab", "lab desc", "Python", 5, True)
    assert r.url == "https://github.com/alice/lab"
    assert r.pushed_at == datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def test_missing_optional_fields_get_safe_defaults():
    r = build_profile("alice", [{"name": "bare"}], [], NOW).repos[0]
    assert (r.description, r.language, r.stars, r.fork, r.pushed_at) == ("", "", 0, False, None)
    assert r.url == "https://github.com/alice"


@pytest.mark.parametrize("stars", ["12", -3, True, 1.5])
def test_odd_star_counts_become_zero(stars):
    assert build_profile("alice", [repo("x", stargazers_count=stars)], [], NOW).repos[0].stars == 0


def test_null_description_and_language_become_empty():
    r = build_profile("alice", [repo("x", description=None, language=None, stargazers_count=None)], [], NOW).repos[0]
    assert (r.description, r.language, r.stars) == ("", "", 0)


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "https://evil.com/alice/x", "http://github.com/alice/x", 42, None,
])
def test_links_outside_github_are_replaced_with_the_profile(url):
    r = build_profile("alice", [repo("x", html_url=url)], [], NOW).repos[0]
    assert r.url == "https://github.com/alice"


def test_malformed_repo_entries_are_skipped():
    profile = build_profile("alice", ["junk", None, {"no_name": 1}, {"name": 5}, repo("ok")], [], NOW)
    assert [r.name for r in profile.repos] == ["ok"]


@pytest.mark.parametrize("bad", [None, {"message": "Not Found"}, "oops"])
def test_non_list_responses_give_an_empty_profile(bad):
    profile = build_profile("alice", bad, bad, NOW)
    assert (profile.repos, profile.pushes, profile.active_days, profile.available) == ((), 0, 0, True)


def test_bad_timestamps_are_ignored():
    profile = build_profile("alice", [repo("x", "yesterday")], [push("not a date"), push(None)], NOW)
    assert profile.repos[0].pushed_at is None
    assert profile.pushes == 0


def test_pushes_counted_within_the_last_30_days_only():
    events = [
        push("2026-10-03T09:00:00Z"),
        push("2026-10-03T08:00:00Z"),        # same day: two pushes, one active day
        push("2026-09-20T08:00:00Z"),
        push("2026-09-03T12:00:00Z"),        # exactly 30 days ago: counted
        push("2026-09-03T11:59:59Z"),        # just outside the window
        push("2026-10-02T08:00:00Z", "WatchEvent"),   # starring isn't a push
        "junk",
    ]
    profile = build_profile("alice", [], events, NOW)
    assert profile.pushes == 4
    assert profile.active_days == 3


def test_pushed_label_and_profile_url():
    profile = build_profile("alice", [repo("x", "2026-09-05T00:00:00Z"), repo("y", None)], [], NOW)
    assert profile.repos[0].pushed_label == "Sep 5, 2026"
    assert profile.repos[1].pushed_label == ""
    assert profile.url == "https://github.com/alice"


# ── The service: fetching, caching, failures ─────────────────────────────────

class FakeGitHub:
    """Stands in for the HTTP call: records URLs and returns canned JSON."""

    def __init__(self, repos=None, events=None, error=None):
        self.repos = [repo("lab")] if repos is None else repos
        self.events = [] if events is None else events
        self.error = error
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.repos if "/repos" in url else self.events


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_profile_fetches_repos_and_public_events():
    fake = FakeGitHub()
    profile = GitHubService(fetch=fake, clock=FakeClock()).profile("alice")
    assert profile.available
    assert [r.name for r in profile.repos] == ["lab"]
    assert fake.urls == [
        "https://api.github.com/users/alice/repos?sort=pushed&per_page=30",
        "https://api.github.com/users/alice/events/public?per_page=100",
    ]


def test_invalid_username_is_rejected_before_any_request():
    fake = FakeGitHub()
    with pytest.raises(ValueError):
        GitHubService(fetch=fake).profile("../../admin")
    assert fake.urls == []


def test_profile_is_cached_within_the_ttl():
    fake, clock = FakeGitHub(), FakeClock()
    service = GitHubService(fetch=fake, clock=clock)
    first = service.profile("alice")
    clock.now += gh.CACHE_SECONDS - 1
    assert service.profile("ALICE") is first     # cache key ignores case, like GitHub
    assert len(fake.urls) == 2


def test_profile_is_refetched_after_the_ttl():
    fake, clock = FakeGitHub(), FakeClock()
    service = GitHubService(fetch=fake, clock=clock)
    service.profile("alice")
    clock.now += gh.CACHE_SECONDS
    service.profile("alice")
    assert len(fake.urls) == 4


@pytest.mark.parametrize("error", [
    requests.ConnectionError("offline"),
    requests.HTTPError("404 Not Found"),
    requests.Timeout("slow"),
    ValueError("not JSON"),
])
def test_failures_give_an_unavailable_profile_that_is_not_cached(error):
    fake = FakeGitHub(error=error)
    service = GitHubService(fetch=fake, clock=FakeClock())
    profile = service.profile("alice")
    assert not profile.available
    assert (profile.repos, profile.pushes, profile.active_days) == ((), 0, 0)
    service.profile("alice")
    assert len(fake.urls) == 2     # tried again: one failing call per view


def test_forget_drops_the_cached_profile():
    fake = FakeGitHub()
    service = GitHubService(fetch=fake, clock=FakeClock())
    service.profile("alice")
    service.forget("Alice")
    service.profile("alice")
    assert len(fake.urls) == 4


def test_forget_unknown_or_empty_name_is_harmless():
    service = GitHubService(fetch=FakeGitHub())
    service.forget("nobody")
    service.forget(None)


def test_http_get_sends_json_accept_header_and_timeout(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            seen["checked"] = True

        def json(self):
            return [1]

    def fake_get(url, timeout, headers):
        seen.update(url=url, timeout=timeout, headers=headers)
        return Response()

    monkeypatch.setattr(gh.requests, "get", fake_get)
    assert gh._http_get("https://api.github.com/users/alice/repos") == [1]
    assert seen["timeout"] == 5 and seen["checked"]
    assert seen["headers"]["Accept"] == "application/vnd.github+json"
    assert "Authorization" not in seen["headers"]

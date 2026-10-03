"""Linked GitHub profiles: a user's public repositories and recent push activity.

Read-only and keyless. Only GitHub's public REST API is used, so the app never
asks for or stores a GitHub password or token (in line with ADR 5). The HTTP
call and the clock are passed in, so the tests run on canned responses and
never touch the network.
"""
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

API = "https://api.github.com"
PROFILE_URL = "https://github.com/"
# GitHub usernames: 1-39 characters, letters, digits and single hyphens,
# not starting or ending with a hyphen. Validating this strictly also means
# nothing but a plain name can ever end up in the API URL we build.
USERNAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
CACHE_SECONDS = 15 * 60     # GitHub allows 60 unauthenticated requests per hour per IP
REPOS_SHOWN = 8
ACTIVITY_DAYS = 30


@dataclass(frozen=True)
class Repo:
    name: str
    description: str
    url: str
    language: str
    stars: int
    fork: bool
    pushed_at: Optional[datetime]

    @property
    def pushed_label(self):
        return f"{self.pushed_at:%b} {self.pushed_at.day}, {self.pushed_at.year}" if self.pushed_at else ""


@dataclass(frozen=True)
class Profile:
    username: str
    repos: tuple
    pushes: int          # push events in the last ACTIVITY_DAYS days
    active_days: int     # distinct days with at least one push
    available: bool      # False when GitHub couldn't be reached or the user doesn't exist

    @property
    def url(self):
        return PROFILE_URL + self.username


def valid_username(name):
    # fullmatch, not match: "$" would also accept a trailing newline.
    return isinstance(name, str) and USERNAME_RE.fullmatch(name) is not None


def parse_username(raw):
    """Accept 'name', '@name' or 'https://github.com/name' and return the bare name, or None if invalid."""
    name = (raw or "").strip()
    for prefix in ("https://github.com/", "http://github.com/", "https://www.github.com/",
                   "www.github.com/", "github.com/"):
        if name.lower().startswith(prefix):
            name = name[len(prefix):].strip("/")
            break
    if name.startswith("@"):
        name = name[1:]
    return name if valid_username(name) else None


def _parse_time(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _safe_url(value, fallback):
    """Only ever link to github.com, whatever the response says."""
    return value if isinstance(value, str) and value.startswith(PROFILE_URL) else fallback


def build_profile(username, repos_json, events_json, now):
    """Turn the two API responses into a Profile. Malformed entries are skipped, not trusted."""
    profile_url = PROFILE_URL + username
    repos = []
    for r in repos_json if isinstance(repos_json, list) else []:
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            continue
        repos.append(Repo(
            name=r["name"],
            description=r.get("description") or "",
            url=_safe_url(r.get("html_url"), profile_url),
            language=r.get("language") or "",
            stars=_count(r.get("stargazers_count")),
            fork=bool(r.get("fork")),
            pushed_at=_parse_time(r.get("pushed_at")),
        ))
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    repos.sort(key=lambda repo: repo.pushed_at or oldest, reverse=True)

    since = now - timedelta(days=ACTIVITY_DAYS)
    push_times = [
        when for e in (events_json if isinstance(events_json, list) else [])
        if isinstance(e, dict) and e.get("type") == "PushEvent"
        for when in [_parse_time(e.get("created_at"))]
        if when is not None and when >= since
    ]
    return Profile(username, tuple(repos[:REPOS_SHOWN]), len(push_times),
                   len({t.date() for t in push_times}), True)


def _http_get(url):
    response = requests.get(
        url, timeout=5,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "cyberroadmap"},
    )
    response.raise_for_status()
    return response.json()


class GitHubService:
    """Facade over GitHub's public API, with a small in-process cache.

    One process means one cache; it only saves repeat requests (GitHub's
    hourly limit), it is not storage, so nothing here touches the database.
    """

    def __init__(self, fetch=_http_get, clock=time.time):
        self._fetch = fetch
        self._clock = clock
        self._cache = {}

    def profile(self, username):
        if not valid_username(username):
            raise ValueError("not a valid GitHub username")
        key = username.lower()
        cached = self._cache.get(key)
        if cached and self._clock() - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            repos = self._fetch(f"{API}/users/{username}/repos?sort=pushed&per_page=30")
            events = self._fetch(f"{API}/users/{username}/events/public?per_page=100")
        except (requests.RequestException, ValueError):
            # Not cached, so the next page view tries again.
            return Profile(username, (), 0, 0, False)
        profile = build_profile(username, repos, events, datetime.now(timezone.utc))
        self._cache[key] = (self._clock(), profile)
        return profile

    def forget(self, username):
        self._cache.pop((username or "").lower(), None)

"""Tokens, the connection string, the migration runner's file rules, the progress client."""
import os

import pytest
import requests

import auth
import db
import migrate
from progress_client import ProgressClient, ProgressUnavailable


# ── auth ────────────────────────────────────────────────────────────────────

def test_token_round_trip_and_tampering():
    token = auth.issue(7, 3)
    assert auth.verify(token) == (7, 3)
    with pytest.raises(auth.InvalidToken):
        auth.verify(token[:-2] + "xx")


def test_token_expires(monkeypatch):
    token = auth.issue(7, 0)
    monkeypatch.setenv("TOKEN_TTL_S", "-1")
    with pytest.raises(auth.InvalidToken):
        auth.verify(token)


def test_missing_or_short_secret_refuses_to_issue(monkeypatch):
    monkeypatch.setenv("TOKEN_SECRET", "short")
    with pytest.raises(RuntimeError):
        auth.issue(1, 0)


@pytest.mark.parametrize("header,expected", [
    ("Bearer abc", "abc"), ("bearer abc", "abc"), ("Basic abc", None), ("Bearer ", None), ("", None),
])
def test_bearer_header_parsing(header, expected):
    assert auth.bearer({"Authorization": header}) == expected


# ── DATABASE_URL ────────────────────────────────────────────────────────────

def test_parse_url_decodes_password_and_options():
    kw = db.parse_url("mssql+pymssql://svc_user:p%40ss%3Aword@srv.database.windows.net:1433/app-db"
                      "?encryption=require&login_timeout=5")
    assert kw["server"] == "srv.database.windows.net" and kw["port"] == "1433"
    assert kw["user"] == "svc_user" and kw["password"] == "p@ss:word"
    assert kw["database"] == "app-db"
    assert kw["encryption"] == "require" and kw["login_timeout"] == 5


@pytest.mark.parametrize("url", ["", "sqlite:///x.db", "mssql+pymssql://u:p@host:1433/"])
def test_parse_url_rejects_bad_urls(url):
    with pytest.raises(ValueError):
        db.parse_url(url)


def test_connect_gives_up_after_the_deadline(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mssql+pymssql://u:p@127.0.0.1:1/none?login_timeout=1")
    with pytest.raises(db.DatabaseUnavailable):
        db.Database().connect(deadline_s=0)


# ── migrations ──────────────────────────────────────────────────────────────

def test_pending_files_in_order_and_skips_applied(tmp_path):
    for name in ["002_add_x.sql", "001_init.sql", "notes.txt", "003_more.sql"]:
        (tmp_path / name).write_text("SELECT 1")
    assert migrate.pending_files(tmp_path, {"001_init.sql"}) == ["002_add_x.sql", "003_more.sql"]


def test_duplicate_version_numbers_are_refused(tmp_path):
    (tmp_path / "002_a.sql").write_text("")
    (tmp_path / "002_b.sql").write_text("")
    with pytest.raises(RuntimeError):
        migrate.pending_files(tmp_path, set())


def test_batches_split_on_go_lines():
    sql = "CREATE TABLE a (id INT);\nGO\n\n  go  \nALTER TABLE a ADD b INT;\nGO\n"
    assert migrate.batches(sql) == ["CREATE TABLE a (id INT);", "ALTER TABLE a ADD b INT;"]


def test_shipped_migrations_are_well_formed():
    names = sorted(os.listdir(migrate.MIGRATIONS_DIR))
    assert names[0] == "001_init.sql"
    assert all(migrate.FILE_RE.match(n) for n in names)
    for name in names:
        text = open(os.path.join(migrate.MIGRATIONS_DIR, name)).read().upper()
        assert "DROP TABLE" not in text and "DROP DATABASE" not in text   # A2 §4: never lose data


# ── progress client ─────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, result):
        self.result, self.seen = result, []

    def delete(self, url, timeout, headers):
        self.seen.append((url, timeout, headers["Authorization"]))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_progress_client_forwards_token_and_uses_timeout():
    session = FakeSession(FakeResponse(200, {"deleted": 3}))
    client = ProgressClient("http://progress:8000/", timeout_s=1.5, session=session)
    assert client.delete_item_logs("tok", 9) == 3
    assert session.seen == [("http://progress:8000/items/9/logs", 1.5, "Bearer tok")]


@pytest.mark.parametrize("result", [requests.Timeout(), requests.ConnectionError(), FakeResponse(503)])
def test_progress_client_failures_become_unavailable(result):
    client = ProgressClient("http://progress:8000", timeout_s=1, session=FakeSession(result))
    with pytest.raises(ProgressUnavailable):
        client.delete_user_logs("tok")


def test_progress_client_reads_url_and_timeout_from_env(monkeypatch):
    monkeypatch.setenv("PROGRESS_URL", "http://elsewhere:9000")
    monkeypatch.setenv("PROGRESS_TIMEOUT_S", "4")
    client = ProgressClient()
    assert (client.base_url, client.timeout_s) == ("http://elsewhere:9000", 4.0)

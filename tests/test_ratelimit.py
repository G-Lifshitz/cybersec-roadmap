import os
import tempfile
import pytest

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATA_DIR"] = os.path.dirname(tmp.name)

import db
import models.ratelimit as rl

db.DB_PATH = tmp.name
T0 = 1_000_000.0  # fixed fake clock so tests never depend on real time


@pytest.fixture(autouse=True)
def fresh_db():
    db.init_db()
    yield
    with db.get_db() as conn:
        conn.execute("DELETE FROM rate_events")


def test_not_limited_below_threshold():
    for i in range(4):
        rl.record("login_fail", "alice|1.2.3.4", now=T0 + i)
    assert rl.is_limited("login_fail", "alice|1.2.3.4", 5, 900, now=T0 + 10) is False


def test_limited_at_threshold():
    for i in range(5):
        rl.record("login_fail", "alice|1.2.3.4", now=T0 + i)
    assert rl.is_limited("login_fail", "alice|1.2.3.4", 5, 900, now=T0 + 10) is True


def test_window_slides_old_events_expire():
    for i in range(5):
        rl.record("login_fail", "k", now=T0 + i)
    # 900s after the first event, it drops out of the window -> 4 left, unlocked
    assert rl.is_limited("login_fail", "k", 5, 900, now=T0 + 900.5) is False


def test_keys_and_kinds_are_independent():
    for i in range(5):
        rl.record("login_fail", "alice|ip1", now=T0 + i)
    assert rl.is_limited("login_fail", "bob|ip1", 5, 900, now=T0 + 10) is False
    assert rl.is_limited("register", "alice|ip1", 5, 900, now=T0 + 10) is False


def test_retry_after_counts_down_to_oldest_expiry():
    rl.record("login_fail", "k", now=T0)
    rl.record("login_fail", "k", now=T0 + 100)
    assert rl.retry_after("login_fail", "k", 900, now=T0 + 300) == 601
    assert rl.retry_after("login_fail", "nobody", 900, now=T0) == 0


def test_clear_resets_key():
    for i in range(5):
        rl.record("login_fail", "k", now=T0 + i)
    rl.clear("login_fail", "k")
    assert rl.count_recent("login_fail", "k", 900, now=T0 + 10) == 0


def test_prune_removes_only_old_rows():
    rl.record("register", "ip", now=T0)
    rl.record("register", "ip", now=T0 + 90_000)
    rl.prune(older_than=86_400, now=T0 + 90_001)
    assert rl.count_recent("register", "ip", 10**9, now=T0 + 90_001) == 1

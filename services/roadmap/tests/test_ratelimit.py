"""Rate limiter against SQL Server. The clock is passed in, so nothing sleeps."""
import pytest

import models.ratelimit as rl

pytestmark = pytest.mark.db
T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def _clean(clean_db):
    pass


def test_limited_at_threshold_and_window_slides():
    for i in range(5):
        rl.record("login_fail", "georgy|1.1.1.1", now=T0 + i)
    assert rl.is_limited("login_fail", "georgy|1.1.1.1", 5, 900, now=T0 + 10)
    assert not rl.is_limited("login_fail", "georgy|1.1.1.1", 5, 900, now=T0 + 901)


def test_keys_and_kinds_are_independent():
    for _ in range(5):
        rl.record("login_fail", "a")
    assert not rl.is_limited("login_fail", "b", 5, 900)
    assert not rl.is_limited("register", "a", 5, 900)


def test_retry_after_counts_down_to_oldest_expiry():
    rl.record("register", "ip", now=T0)
    assert rl.retry_after("register", "ip", 60, now=T0 + 10) == 51
    assert rl.retry_after("register", "other", 60, now=T0) == 0


def test_clear_and_prune():
    rl.record("login_fail", "k", now=T0)
    rl.record("login_fail", "old", now=T0 - 10_000)
    rl.prune(older_than=3600, now=T0)
    assert rl.count_recent("login_fail", "old", 100_000, now=T0) == 0
    rl.clear("login_fail", "k")
    assert rl.count_recent("login_fail", "k", 900, now=T0 + 1) == 0

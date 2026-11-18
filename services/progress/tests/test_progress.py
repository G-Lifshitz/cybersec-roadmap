"""Progress model against SQL Server. Logs are owner-scoped by their own user_id now."""
import pytest

import models.progress as progress

pytestmark = pytest.mark.db
ALICE, BOB = 1, 2


@pytest.fixture(autouse=True)
def _clean(clean_db):
    pass


def test_add_and_read_logs_newest_first():
    first = progress.add_log(ALICE, 10, 20, "fair", "recon", 30)
    second = progress.add_log(ALICE, 10, 60, "hard", "", 45)
    logs = progress.get_logs_for_item(ALICE, 10)
    assert [log["id"] for log in logs] == [second, first]
    assert logs[0]["completion_pct"] == 60


def test_logs_are_owner_scoped():
    progress.add_log(ALICE, 10, 20, None, "", 0)
    assert progress.get_logs_for_item(BOB, 10) == []
    assert progress.all_logs(BOB) == []
    assert progress.delete_for_item(BOB, 10) == 0
    assert len(progress.all_logs(ALICE)) == 1


def test_latest_completion_per_item():
    progress.add_log(ALICE, 10, 20, None, "", 0)
    progress.add_log(ALICE, 10, 70, None, "", 0)
    progress.add_log(ALICE, 11, 100, None, "", 0)
    assert progress.latest_completion_by_item(ALICE) == {10: 70, 11: 100}


def test_time_entries_and_rated_logs():
    progress.add_log(ALICE, 10, 20, "hard", "", 45)
    progress.add_log(ALICE, 11, 20, None, "", None)
    entries = progress.time_entries(ALICE)
    assert [(e["item_id"], e["minutes"]) for e in entries] == [(10, 45), (11, 0)]
    assert progress.rated_logs(ALICE) == [{"item_id": 10, "felt_difficulty": "hard"}]


def test_completion_outside_0_100_is_refused_by_the_database():
    with pytest.raises(Exception):
        progress.add_log(ALICE, 10, 150, None, "", 0)


def test_delete_for_item_and_for_user():
    progress.add_log(ALICE, 10, 20, None, "", 0)
    progress.add_log(ALICE, 11, 20, None, "", 0)
    progress.add_log(BOB, 12, 20, None, "", 0)
    assert progress.delete_for_item(ALICE, 10) == 1
    assert progress.delete_for_user(ALICE) == 1
    assert len(progress.all_logs(BOB)) == 1

"""Stored assessment attempts against SQL Server."""
import pytest

import models.assessment as assessment
import models.users as users

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _clean(clean_db):
    pass


def test_save_get_and_history_are_owner_scoped():
    alice = users.create_user("alice", "correct-horse")
    bob = users.create_user("bob", "correct-horse")
    first = assessment.save(alice, "pentest", {"q1": 2}, 2, 3, "intermediate")
    second = assessment.save(alice, "pentest", {"q1": 3}, 3, 3, "advanced")
    assert assessment.get(first, alice)["answers"] == {"q1": 2}
    assert assessment.get(first, bob) is None
    history = assessment.history(alice)
    assert [h["id"] for h in history] == [second, first]
    assert history[0]["percent"] == 100
    assert assessment.history(alice, limit=1)[0]["id"] == second

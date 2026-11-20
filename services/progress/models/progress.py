"""Progress logs: what a user has actually done on an item.

Every query filters on the log's own user_id. Anything that needs an item's
skill tags (weak skills, minutes per skill) gets them from the roadmap service
and joins in Python; see domain/insights.py.
"""
from db import transaction

FELT_DIFFICULTIES = ("easy", "fair", "hard", "brutal")
_COLUMNS = "id, item_id, checked_in_at, completion_pct, felt_difficulty, notes, time_spent_mins"


def get_logs_for_item(user_id, item_id):
    with transaction() as cur:
        cur.execute(f"""SELECT {_COLUMNS} FROM progress_logs
                        WHERE user_id = %s AND item_id = %s
                        ORDER BY checked_in_at DESC, id DESC""", (user_id, item_id))
        return cur.fetchall()


def add_log(user_id, item_id, completion_pct, felt_difficulty, notes, time_spent_mins):
    """Insert a log and return its id. The caller has already checked the item is this user's."""
    with transaction() as cur:
        cur.execute(
            """INSERT INTO progress_logs
               (user_id, item_id, completion_pct, felt_difficulty, notes, time_spent_mins)
               OUTPUT INSERTED.id VALUES (%s, %s, %s, %s, %s, %s)""",
            (user_id, item_id, completion_pct, felt_difficulty, notes, time_spent_mins),
        )
        return cur.fetchone()["id"]


def latest_completion_by_item(user_id):
    """{item_id: completion_pct of the most recent log} for every item this user has logged."""
    with transaction() as cur:
        cur.execute("""SELECT item_id, completion_pct FROM (
                           SELECT item_id, completion_pct,
                                  ROW_NUMBER() OVER (PARTITION BY item_id
                                                     ORDER BY checked_in_at DESC, id DESC) AS rn
                           FROM progress_logs WHERE user_id = %s) AS latest
                       WHERE rn = 1""", (user_id,))
        return {row["item_id"]: row["completion_pct"] for row in cur.fetchall()}


def rated_logs(user_id):
    """(item_id, felt_difficulty) for every log with a difficulty rating."""
    with transaction() as cur:
        cur.execute("""SELECT item_id, felt_difficulty FROM progress_logs
                       WHERE user_id = %s AND felt_difficulty IS NOT NULL""", (user_id,))
        return cur.fetchall()


def time_entries(user_id):
    """(item_id, day, minutes) for every log; a log without a time counts as 0 minutes."""
    with transaction() as cur:
        cur.execute("""SELECT item_id, CONVERT(date, checked_in_at) AS day,
                              COALESCE(time_spent_mins, 0) AS minutes
                       FROM progress_logs WHERE user_id = %s ORDER BY id""", (user_id,))
        return cur.fetchall()


def all_logs(user_id):
    """Every log this user has, oldest first."""
    with transaction() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM progress_logs WHERE user_id = %s ORDER BY id", (user_id,))
        return cur.fetchall()


def delete_for_item(user_id, item_id):
    """Remove an item's logs (called by roadmap when the item is deleted). Returns rows removed."""
    with transaction() as cur:
        cur.execute("DELETE FROM progress_logs WHERE user_id = %s AND item_id = %s", (user_id, item_id))
        return cur.rowcount


def delete_for_user(user_id):
    """Remove every log of a user (called by roadmap before it deletes the account)."""
    with transaction() as cur:
        cur.execute("DELETE FROM progress_logs WHERE user_id = %s", (user_id,))
        return cur.rowcount

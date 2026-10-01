from db import get_db


def get_logs_for_item(item_id):
    with get_db() as conn:
        return conn.execute(
            """SELECT * FROM progress_logs
               WHERE item_id = ?
               ORDER BY checked_in_at DESC, id DESC""",
            (item_id,),
        ).fetchall()


def add_log(item_id, completion_pct, felt_difficulty, notes, time_spent_mins):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO progress_logs
               (item_id, completion_pct, felt_difficulty, notes, time_spent_mins)
               VALUES (?, ?, ?, ?, ?)""",
            (item_id, completion_pct, felt_difficulty, notes, time_spent_mins),
        )
        # Auto-update parent item status based on completion
        if completion_pct >= 100:
            conn.execute(
                "UPDATE roadmap_items SET status = 'completed' WHERE id = ?",
                (item_id,),
            )
        elif completion_pct > 0:
            conn.execute(
                "UPDATE roadmap_items SET status = 'in_progress' WHERE id = ?",
                (item_id,),
            )
        return cur.lastrowid


def latest_completion(item_id):
    """Return the most recent completion_pct for an item."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT completion_pct FROM progress_logs
               WHERE item_id = ?
               ORDER BY checked_in_at DESC, id DESC LIMIT 1""",
            (item_id,),
        ).fetchone()
    return row["completion_pct"] if row else 0


def weak_skills(user_id):
    """
    Return skill tags where this user frequently finds things hard/brutal
    (more than 50% of their rated logs for that tag are 'hard' or 'brutal').
    Used to personalise YouTube recommendations.
    """
    hard_values = {"hard", "brutal"}
    with get_db() as conn:
        rows = conn.execute(
            """SELECT ri.skill_tags, pl.felt_difficulty
               FROM progress_logs pl
               JOIN roadmap_items ri ON ri.id = pl.item_id
               WHERE pl.felt_difficulty IS NOT NULL
                 AND ri.user_id = ?""",
            (user_id,),
        ).fetchall()

    tag_counts = {}
    for row in rows:
        tags = [t.strip() for t in (row["skill_tags"] or "").split(",") if t.strip()]
        for tag in tags:
            if tag not in tag_counts:
                tag_counts[tag] = {"total": 0, "hard": 0}
            tag_counts[tag]["total"] += 1
            if row["felt_difficulty"] in hard_values:
                tag_counts[tag]["hard"] += 1

    weak = [
        tag for tag, counts in tag_counts.items()
        if counts["total"] > 0 and counts["hard"] / counts["total"] > 0.5
    ]
    return weak


def total_time_spent(user_id):
    with get_db() as conn:
        row = conn.execute(
            """SELECT SUM(pl.time_spent_mins) AS total
               FROM progress_logs pl
               JOIN roadmap_items ri ON ri.id = pl.item_id
               WHERE ri.user_id = ?""",
            (user_id,),
        ).fetchone()
    return row["total"] or 0


def logs_for_user(user_id):
    """Every log on this user's items, oldest first, with the item title (used by the data export).

    Logs have no user_id of their own, so ownership comes through the JOIN (ADR 3).
    """
    with get_db() as conn:
        return conn.execute(
            """SELECT pl.id, pl.item_id, ri.title AS item_title, pl.checked_in_at,
                      pl.completion_pct, pl.felt_difficulty, pl.notes, pl.time_spent_mins
               FROM progress_logs pl
               JOIN roadmap_items ri ON ri.id = pl.item_id
               WHERE ri.user_id = ?
               ORDER BY pl.id""",
            (user_id,),
        ).fetchall()

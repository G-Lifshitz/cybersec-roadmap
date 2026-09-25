from db import get_db


def get_all(status=None, skill=None):
    query = "SELECT * FROM roadmap_items WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if skill:
        query += " AND skill_tags LIKE ?"
        params.append(f"%{skill}%")
    query += " ORDER BY priority DESC, created_at ASC"
    with get_db() as conn:
        return conn.execute(query, params).fetchall()


def get_by_id(item_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM roadmap_items WHERE id = ?", (item_id,)
        ).fetchone()


def create(title, type_, platform, url, skill_tags, difficulty, priority):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO roadmap_items
               (title, type, platform, url, skill_tags, difficulty, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (title, type_, platform, url, skill_tags, difficulty, priority),
        )
        return cur.lastrowid


def update_status(item_id, status):
    with get_db() as conn:
        conn.execute(
            "UPDATE roadmap_items SET status = ? WHERE id = ?",
            (status, item_id),
        )


def delete(item_id):
    with get_db() as conn:
        conn.execute("DELETE FROM roadmap_items WHERE id = ?", (item_id,))


def get_skill_summary():
    """Return each skill tag and counts by status — drives the dashboard."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT skill_tags, status FROM roadmap_items"
        ).fetchall()

    summary = {}
    for row in rows:
        tags = [t.strip() for t in (row["skill_tags"] or "").split(",") if t.strip()]
        for tag in tags:
            if tag not in summary:
                summary[tag] = {"not_started": 0, "in_progress": 0, "completed": 0}
            summary[tag][row["status"]] = summary[tag].get(row["status"], 0) + 1
    return summary

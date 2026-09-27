from db import get_db

# Columns a user may change through the edit form. Anything not listed here
# (id, created_at, status) can't be overwritten by update().
EDITABLE_FIELDS = ("title", "type", "platform", "url", "skill_tags", "difficulty", "priority")


def get_all(status=None, skill=None, search=None, type_=None):
    """Return roadmap items, optionally filtered.

    status: exact match on status column
    skill:  a single tag; matched against the comma-separated skill_tags
    search: free text, matched against title and platform
    type_:  exact match on item type (course, cert, lab, ...)
    """
    query = "SELECT * FROM roadmap_items WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if type_:
        query += " AND type = ?"
        params.append(type_)
    if search:
        query += " AND (title LIKE ? OR platform LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    query += " ORDER BY priority DESC, created_at ASC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    # Tag filtering is done in Python rather than with LIKE so that "web"
    # doesn't also match "web3" or "webapp".
    if skill:
        skill = skill.strip().lower()
        rows = [r for r in rows if skill in _split_tags(r["skill_tags"])]
    return rows


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
            (title, type_, platform, url, normalise_tags(skill_tags), difficulty, priority),
        )
        return cur.lastrowid


def update(item_id, **fields):
    """Update the editable fields of an item. Unknown keys are ignored.

    Returns True if a row was changed, False if the item doesn't exist.
    """
    changes = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    if not changes:
        return False
    if "skill_tags" in changes:
        changes["skill_tags"] = normalise_tags(changes["skill_tags"])

    # Column names come from EDITABLE_FIELDS (a fixed whitelist), never from
    # user input, so building the SET clause with an f-string is safe.
    set_clause = ", ".join(f"{col} = ?" for col in changes)
    with get_db() as conn:
        cur = conn.execute(
            f"UPDATE roadmap_items SET {set_clause} WHERE id = ?",
            (*changes.values(), item_id),
        )
        return cur.rowcount > 0


def update_status(item_id, status):
    with get_db() as conn:
        conn.execute(
            "UPDATE roadmap_items SET status = ? WHERE id = ?",
            (status, item_id),
        )


def delete(item_id):
    with get_db() as conn:
        conn.execute("DELETE FROM roadmap_items WHERE id = ?", (item_id,))


def get_all_tags():
    """Sorted list of every distinct skill tag in use — feeds the filter dropdown."""
    with get_db() as conn:
        rows = conn.execute("SELECT skill_tags FROM roadmap_items").fetchall()
    tags = set()
    for row in rows:
        tags.update(_split_tags(row["skill_tags"]))
    return sorted(tags)


def get_skill_summary():
    """Return each skill tag and counts by status — drives the dashboard."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT skill_tags, status FROM roadmap_items"
        ).fetchall()

    summary = {}
    for row in rows:
        for tag in _split_tags(row["skill_tags"]):
            if tag not in summary:
                summary[tag] = {"not_started": 0, "in_progress": 0, "completed": 0}
            summary[tag][row["status"]] = summary[tag].get(row["status"], 0) + 1
    return summary


def normalise_tags(raw):
    """'Web, NETWORK ,, web' -> 'web,network' (lowercase, trimmed, de-duplicated, order kept)."""
    seen = []
    for tag in _split_tags(raw):
        if tag not in seen:
            seen.append(tag)
    return ",".join(seen)


def _split_tags(raw):
    return [t.strip().lower() for t in (raw or "").split(",") if t.strip()]


def get_status_counts():
    """{'not_started': n, 'in_progress': n, 'completed': n, 'total': n} across all items."""
    counts = {"not_started": 0, "in_progress": 0, "completed": 0}
    with get_db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM roadmap_items GROUP BY status"
        ).fetchall()
    for row in rows:
        counts[row["status"]] = row["n"]
    counts["total"] = sum(counts.values())
    return counts

"""Roadmap items: what a user plans to learn. Every query filters on user_id.

Ported from SQLite: ? placeholders became %s, cursor.lastrowid became
OUTPUT INSERTED.id, and the ON DELETE CASCADE to progress_logs is gone,
because the logs now live in the progress service's database (ADR 6).
"""
from db import transaction
from domain.tags import normalise_tags, split_tags

# Columns a user may change through the edit form. Anything not listed here
# (id, user_id, created_at, status) can't be overwritten by update().
EDITABLE_FIELDS = ("title", "type", "platform", "url", "skill_tags", "difficulty", "priority")
STATUSES = ("not_started", "in_progress", "completed")

_COLUMNS = "id, user_id, title, type, platform, url, skill_tags, difficulty, priority, status, created_at, updated_at"


def get_all(user_id, status=None, skill=None, search=None, type_=None):
    """One user's items, optionally filtered, highest priority first."""
    query = f"SELECT {_COLUMNS} FROM roadmap_items WHERE user_id = %s"
    params = [user_id]
    if status:
        query += " AND status = %s"
        params.append(status)
    if type_:
        query += " AND type = %s"
        params.append(type_)
    if search:
        query += " AND (title LIKE %s OR platform LIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    query += " ORDER BY priority DESC, created_at ASC, id ASC"

    with transaction() as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

    # Tag filtering is done in Python rather than with LIKE so that "web"
    # doesn't also match "web3" or "webapp".
    if skill:
        skill = skill.strip().lower()
        rows = [r for r in rows if skill in split_tags(r["skill_tags"])]
    return rows


def get_by_id(item_id, user_id):
    """The item only if it belongs to user_id, else None (no IDOR)."""
    with transaction() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM roadmap_items WHERE id = %s AND user_id = %s",
                    (item_id, user_id))
        return cur.fetchone()


def _insert(cur, user_id, title, type_, platform, url, skill_tags, difficulty, priority):
    cur.execute(
        """INSERT INTO roadmap_items
           (user_id, title, type, platform, url, skill_tags, difficulty, priority)
           OUTPUT INSERTED.id
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (user_id, title, type_, platform, url, normalise_tags(skill_tags), difficulty, priority),
    )
    return cur.fetchone()["id"]


def create(user_id, title, type_, platform, url, skill_tags, difficulty, priority):
    with transaction() as cur:
        return _insert(cur, user_id, title, type_, platform, url, skill_tags, difficulty, priority)


def create_many(user_id, items):
    """Add several items, skipping titles this user already has (case and spaces ignored).

    items: dicts with title, type, platform, url, skill_tags, difficulty, priority.
    Returns how many were created.
    """
    with transaction() as cur:
        cur.execute("SELECT title FROM roadmap_items WHERE user_id = %s", (user_id,))
        existing = {row["title"].strip().lower() for row in cur.fetchall()}
        created = 0
        for item in items:
            key = item["title"].strip().lower()
            if key in existing:
                continue
            _insert(cur, user_id, item["title"].strip(), item["type"], item["platform"], item["url"],
                    item["skill_tags"], item["difficulty"], item["priority"])
            existing.add(key)
            created += 1
        return created


def update(item_id, user_id, **fields):
    """Update the editable fields of an item. Unknown keys are ignored.

    True if a row changed, False if the item doesn't exist or isn't this user's.
    """
    changes = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    if not changes:
        return False
    if "skill_tags" in changes:
        changes["skill_tags"] = normalise_tags(changes["skill_tags"])
    # Column names come from EDITABLE_FIELDS (a fixed whitelist), never from
    # user input, so building the SET clause with an f-string is safe.
    set_clause = ", ".join(f"{col} = %s" for col in changes) + ", updated_at = SYSUTCDATETIME()"
    with transaction() as cur:
        cur.execute(f"UPDATE roadmap_items SET {set_clause} WHERE id = %s AND user_id = %s",
                    (*changes.values(), item_id, user_id))
        return cur.rowcount > 0


def update_status(item_id, user_id, status):
    """Set the status. True if the item exists and is this user's."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    with transaction() as cur:
        cur.execute("UPDATE roadmap_items SET status = %s, updated_at = SYSUTCDATETIME() WHERE id = %s AND user_id = %s",
                    (status, item_id, user_id))
        return cur.rowcount > 0


def delete(item_id, user_id):
    """Delete an item. Its logs are in the progress service and are removed there (ADR 7)."""
    with transaction() as cur:
        cur.execute("DELETE FROM roadmap_items WHERE id = %s AND user_id = %s", (item_id, user_id))
        return cur.rowcount > 0


def get_all_tags(user_id):
    """Sorted list of every distinct skill tag this user has (feeds the filter dropdown)."""
    with transaction() as cur:
        cur.execute("SELECT skill_tags FROM roadmap_items WHERE user_id = %s", (user_id,))
        rows = cur.fetchall()
    tags = set()
    for row in rows:
        tags.update(split_tags(row["skill_tags"]))
    return sorted(tags)


def get_skill_summary(user_id):
    """Each skill tag with item counts by status (the dashboard)."""
    with transaction() as cur:
        cur.execute("SELECT skill_tags, status FROM roadmap_items WHERE user_id = %s", (user_id,))
        rows = cur.fetchall()
    summary = {}
    for row in rows:
        for tag in split_tags(row["skill_tags"]):
            counts = summary.setdefault(tag, {s: 0 for s in STATUSES})
            counts[row["status"]] = counts.get(row["status"], 0) + 1
    return summary


def get_status_counts(user_id):
    """{'not_started': n, 'in_progress': n, 'completed': n, 'total': n}."""
    counts = {s: 0 for s in STATUSES}
    with transaction() as cur:
        cur.execute("SELECT status, COUNT(*) AS n FROM roadmap_items WHERE user_id = %s GROUP BY status",
                    (user_id,))
        for row in cur.fetchall():
            counts[row["status"]] = row["n"]
    counts["total"] = sum(counts.values())
    return counts

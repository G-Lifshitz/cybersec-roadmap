"""Joins that used to be SQL, now done in Python across the seam.

In Assignment 1, weak_skills() and time_entries() JOINed progress_logs with
roadmap_items to read each item's skill tags. The items now live in the
roadmap service, so the routes fetch them over HTTP once (GET /items) and pass
{item_id: skill_tags} in here. Pure functions, no I/O, unit-tested directly.
"""
from domain.tags import split_tags

HARD_VALUES = {"hard", "brutal"}
WEAK_THRESHOLD = 0.5   # more than half of a tag's rated logs felt hard


def status_for_completion(completion_pct):
    """The item status a new log implies: the rule from Assignment 1's add_log()."""
    if completion_pct >= 100:
        return "completed"
    if completion_pct > 0:
        return "in_progress"
    return None   # a 0% log doesn't change the item's status


def weak_skills(rated_logs, tags_by_item):
    """Tags where more than half of this user's rated logs were 'hard' or 'brutal'.

    rated_logs: [{"item_id", "felt_difficulty"}]; tags_by_item: {item_id: "web,network"}.
    Logs whose item no longer exists on the roadmap are ignored.
    """
    counts = {}
    for log in rated_logs:
        if log["item_id"] not in tags_by_item:
            continue
        for tag in split_tags(tags_by_item[log["item_id"]]):
            total, hard = counts.get(tag, (0, 0))
            counts[tag] = (total + 1, hard + (log["felt_difficulty"] in HARD_VALUES))
    return sorted(tag for tag, (total, hard) in counts.items() if hard / total > WEAK_THRESHOLD)


def with_tags(time_entries, tags_by_item):
    """Add each entry's skill_tags. With tags_by_item None (roadmap down) every entry gets ''."""
    return [
        {**entry, "skill_tags": (tags_by_item or {}).get(entry["item_id"], "")}
        for entry in time_entries
    ]

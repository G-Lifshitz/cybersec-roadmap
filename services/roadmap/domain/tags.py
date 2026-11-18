"""Skill tags are stored as one comma-separated string per item ('web,network')."""


def split_tags(raw):
    """'web, Network,,' -> ['web', 'network']."""
    return [t.strip().lower() for t in (raw or "").split(",") if t.strip()]


def normalise_tags(raw):
    """'Web, NETWORK ,, web' -> 'web,network' (lowercase, trimmed, de-duplicated, order kept)."""
    seen = []
    for tag in split_tags(raw):
        if tag not in seen:
            seen.append(tag)
    return ",".join(seen)

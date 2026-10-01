"""Personal data export: everything stored about one user, as JSON or CSV.

This is the GDPR right of access / data portability. collect() asks each domain
model for the user's own rows (every query is owner-scoped); the rest of the
module only serialises. No SQL here, and no model imports another.
"""
import csv
import io
import json

import models.assessment as assessment_model
import models.progress as progress_model
import models.roadmap as roadmap_model
import models.users as users_model

ITEM_COLUMNS = ("id", "title", "type", "platform", "url", "skill_tags",
                "difficulty", "priority", "status", "created_at")
LOG_COLUMNS = ("id", "item_id", "item_title", "checked_in_at", "completion_pct",
               "felt_difficulty", "notes", "time_spent_mins")

# Spreadsheet apps treat a cell starting with one of these as a formula, so a
# title like "=HYPERLINK(...)" could run when the CSV is opened (CSV injection).
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def collect(user_id):
    """One dict with every table's rows for this user."""
    return {
        "account": users_model.export_account(user_id),
        "roadmap_items": [{col: row[col] for col in ITEM_COLUMNS} for row in roadmap_model.get_all(user_id)],
        "progress_logs": [dict(row) for row in progress_model.logs_for_user(user_id)],
        "assessments": assessment_model.all_for_user(user_id),
        "login_events": [dict(row) for row in users_model.all_logins(user_id)],
    }


def to_json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


def to_csv(rows, columns):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([safe_cell(row[col]) for col in columns])
    return buffer.getvalue()


def safe_cell(value):
    """Prefix text that a spreadsheet would run as a formula with a ' so it stays plain text."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


# Download name -> (body builder, content type). A new format is one new entry.
FORMATS = {
    "data.json": (lambda data: to_json(data), "application/json"),
    "items.csv": (lambda data: to_csv(data["roadmap_items"], ITEM_COLUMNS), "text/csv"),
    "logs.csv": (lambda data: to_csv(data["progress_logs"], LOG_COLUMNS), "text/csv"),
}

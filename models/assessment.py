"""Saved questionnaire attempts. One row per attempt, so retakes show progress.

This module only stores and reads rows; scoring lives in services/assessment.py.
"""
import json

from db import get_db


def save(user_id, field, answers, score, max_score, level):
    """Store one attempt and return its id. answers: {question_id: option_index}."""
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO assessments (user_id, field, answers, score, max_score, level)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, field, json.dumps(answers, sort_keys=True), score, max_score, level),
        )
        return cur.lastrowid


def get(assessment_id, user_id):
    """One attempt with its answers decoded, or None if it isn't this user's (no IDOR)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM assessments WHERE id = ? AND user_id = ?", (assessment_id, user_id)
        ).fetchone()
    if row is None:
        return None
    attempt = dict(row)
    attempt["answers"] = json.loads(attempt["answers"])
    return attempt


def history(user_id, limit=10):
    """This user's attempts, newest first. id DESC also orders attempts made in the same second."""
    with get_db() as conn:
        return conn.execute(
            """SELECT id, field, score, max_score, level, taken_at,
                      CAST(ROUND(100.0 * score / max_score) AS INTEGER) AS percent
               FROM assessments WHERE user_id = ?
               ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()

"""Saved questionnaire attempts. One row per attempt, so retakes show progress.

This module only stores and reads rows; scoring lives in domain/assessment.py.
"""
import json

from db import transaction


def save(user_id, field, answers, score, max_score, level):
    """Store one attempt and return its id. answers: {question_id: option_index}."""
    with transaction() as cur:
        cur.execute(
            """INSERT INTO assessments (user_id, field, answers, score, max_score, level)
               OUTPUT INSERTED.id VALUES (%s, %s, %s, %s, %s, %s)""",
            (user_id, field, json.dumps(answers, sort_keys=True), score, max_score, level),
        )
        return cur.fetchone()["id"]


def get(assessment_id, user_id):
    """One attempt with its answers decoded, or None if it isn't this user's (no IDOR)."""
    with transaction() as cur:
        cur.execute("SELECT * FROM assessments WHERE id = %s AND user_id = %s", (assessment_id, user_id))
        row = cur.fetchone()
    if row is None:
        return None
    return {**row, "answers": json.loads(row["answers"])}


def history(user_id, limit=10):
    """This user's attempts, newest first."""
    with transaction() as cur:
        cur.execute(
            """SELECT TOP (%s) id, field, score, max_score, level, taken_at,
                      CAST(ROUND(100.0 * score / max_score, 0) AS INT) AS [percent]
               FROM assessments WHERE user_id = %s ORDER BY id DESC""",
            (int(limit), user_id),
        )
        return cur.fetchall()

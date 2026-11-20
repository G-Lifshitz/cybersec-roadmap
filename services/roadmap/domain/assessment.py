"""Career questionnaire: turns a user's answers into a level, strengths and gaps.

The questions are data (services/question_bank.py). This module only knows the
*shape* of that data and receives it through the constructor (dependency
inversion), so the tests can pass in a tiny fake bank and the real bank can be
rewritten without touching this code.
"""
from dataclasses import dataclass

LEVELS = ("none", "beginner", "intermediate", "advanced")
LEVEL_LABELS = {
    "none": "Just starting",
    "beginner": "Beginner",
    "intermediate": "Intermediate",
    "advanced": "Advanced",
}
# Minimum share of the maximum score for each level, checked from the top down.
# Changing the cut-offs is a data change here, not a code change in level_for().
LEVEL_THRESHOLDS = (("advanced", 0.75), ("intermediate", 0.45), ("beginner", 0.20))

# Average points per question on one skill (0-3 scale).
STRENGTH_MIN = 2   # at or above: strength
GAP_MAX = 1        # at or below: gap


class AssessmentError(ValueError):
    """Raised with a user-facing message when answers can't be scored."""


@dataclass(frozen=True)
class FieldSummary:
    key: str
    name: str
    blurb: str
    questions: int


@dataclass(frozen=True)
class Result:
    field: str
    field_name: str
    answers: dict        # {question_id: option_index}, cleaned; this is what gets stored
    score: int
    max_score: int
    level: str
    strengths: tuple
    gaps: tuple
    roles: tuple
    freelance: tuple

    @property
    def percent(self):
        return round(100 * self.score / self.max_score) if self.max_score else 0

    @property
    def level_label(self):
        return LEVEL_LABELS[self.level]

    @property
    def scale(self):
        """[(label, state)] for the level bar on the results page: 'past', 'current' or ''."""
        reached = LEVELS.index(self.level)
        return [
            (LEVEL_LABELS[lvl], "current" if i == reached else "past" if i < reached else "")
            for i, lvl in enumerate(LEVELS)
        ]


def level_for(score, max_score):
    """Map a score to a level using LEVEL_THRESHOLDS."""
    share = score / max_score if max_score else 0
    for level, minimum in LEVEL_THRESHOLDS:
        if share >= minimum:
            return level
    return "none"


class Questionnaire:
    """Read-only view of a question bank plus the scoring rules.

    bank: {field_key: {"name", "blurb", "questions": [...], "roles": {...}, "freelance": {...}}}
    """

    def __init__(self, bank):
        self._bank = bank

    def fields(self):
        """Every field, in bank order, for the picker page."""
        return [
            FieldSummary(key, data["name"], data["blurb"], len(data["questions"]))
            for key, data in self._bank.items()
        ]

    def names(self):
        """{field_key: display name}."""
        return {key: data["name"] for key, data in self._bank.items()}

    def field(self, key):
        """The field's data, or None if there's no such field."""
        return self._bank.get(key)

    def score(self, key, submitted):
        """Score one attempt.

        submitted: any mapping of question id -> chosen option index. Values may
        be strings (straight from a form) or ints (from the database). Keys that
        aren't questions in this field are ignored.
        Raises AssessmentError if the field is unknown, a question is unanswered,
        or an answer isn't one of that question's options.
        """
        data = self._bank.get(key)
        if data is None:
            raise AssessmentError("Unknown field.")

        answers, skill_points = {}, {}
        for question in data["questions"]:
            index = self._chosen_index(question, submitted.get(question["id"]))
            answers[question["id"]] = index
            points = question["options"][index]["points"]
            skill_points.setdefault(question["skill"], []).append(points)

        score = sum(sum(p) for p in skill_points.values())
        max_score = sum(max(o["points"] for o in q["options"]) for q in data["questions"])
        level = level_for(score, max_score)
        averages = {skill: sum(p) / len(p) for skill, p in skill_points.items()}
        return Result(
            field=key,
            field_name=data["name"],
            answers=answers,
            score=score,
            max_score=max_score,
            level=level,
            strengths=tuple(s for s, avg in averages.items() if avg >= STRENGTH_MIN),
            gaps=tuple(s for s, avg in averages.items() if avg <= GAP_MAX),
            roles=tuple(data["roles"].get(level, ())),
            freelance=tuple(data["freelance"].get(level, ())),
        )

    @staticmethod
    def _chosen_index(question, raw):
        if raw is None or raw == "":
            raise AssessmentError("Answer every question before submitting.")
        try:
            index = int(raw)
        except (TypeError, ValueError):
            raise AssessmentError("One of the answers isn't a valid option.")
        if not 0 <= index < len(question["options"]):
            raise AssessmentError("One of the answers isn't a valid option.")
        return index

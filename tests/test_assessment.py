"""Scoring logic. Uses a small fake bank injected through the constructor."""
import pytest

from services.assessment import (
    LEVELS, AssessmentError, Questionnaire, level_for,
)
from services.question_bank import FIELDS as REAL_BANK


def _question(qid, skill):
    # Option index -> points: 0 -> 0, 1 -> 3 (best), 2 -> 1, 3 -> 2
    return {
        "id": qid, "difficulty": "beginner", "skill": skill, "text": f"Question {qid}?",
        "options": [{"text": "a", "points": 0}, {"text": "b", "points": 3},
                    {"text": "c", "points": 1}, {"text": "d", "points": 2}],
    }


FAKE_BANK = {
    "alpha": {
        "name": "Alpha field",
        "blurb": "Alpha blurb.",
        "questions": [_question("alpha-1", "skill a"), _question("alpha-2", "skill a"),
                      _question("alpha-3", "skill b"), _question("alpha-4", "skill c")],
        "roles": {"none": ["Intern"], "beginner": ["Junior"], "intermediate": ["Mid"], "advanced": ["Senior"]},
        "freelance": {"none": [], "beginner": [], "intermediate": ["Small gigs"], "advanced": ["Consulting"]},
    },
    "beta": {"name": "Beta field", "blurb": "Beta blurb.", "questions": [_question("beta-1", "x")],
             "roles": {}, "freelance": {}},
}
BEST, WORST, ONE_POINT, TWO_POINTS = 1, 0, 2, 3   # option indexes
quiz = Questionnaire(FAKE_BANK)


def _all(index, field="alpha"):
    return {q["id"]: index for q in FAKE_BANK[field]["questions"]}


def test_all_best_answers_is_advanced_with_every_skill_a_strength():
    result = quiz.score("alpha", _all(BEST))
    assert (result.score, result.max_score, result.percent) == (12, 12, 100)
    assert result.level == "advanced"
    assert result.strengths == ("skill a", "skill b", "skill c")
    assert result.gaps == ()
    assert result.roles == ("Senior",) and result.freelance == ("Consulting",)


def test_all_worst_answers_is_none_with_every_skill_a_gap():
    result = quiz.score("alpha", _all(WORST))
    assert result.score == 0 and result.level == "none"
    assert result.gaps == ("skill a", "skill b", "skill c")
    assert result.roles == ("Intern",) and result.freelance == ()


def test_strengths_and_gaps_use_the_average_per_skill():
    answers = {"alpha-1": BEST, "alpha-2": TWO_POINTS,   # skill a: avg 2.5 -> strength
               "alpha-3": ONE_POINT,                     # skill b: 1 -> gap
               "alpha-4": TWO_POINTS}                    # skill c: 2 -> strength
    result = quiz.score("alpha", answers)
    assert result.strengths == ("skill a", "skill c")
    assert result.gaps == ("skill b",)
    assert result.score == 3 + 2 + 1 + 2


@pytest.mark.parametrize("score, level", [
    (0, "none"), (19, "none"), (20, "beginner"), (44, "beginner"),
    (45, "intermediate"), (74, "intermediate"), (75, "advanced"), (100, "advanced"),
])
def test_level_thresholds(score, level):
    assert level_for(score, 100) == level


def test_zero_max_score_does_not_divide_by_zero():
    assert level_for(0, 0) == "none"


def test_form_strings_are_accepted_and_cleaned_to_ints():
    submitted = {qid: str(i) for qid, i in _all(BEST).items()}
    submitted["csrf_or_other_field"] = "ignored"
    result = quiz.score("alpha", submitted)
    assert result.answers == _all(BEST)          # ints, and only real question ids


@pytest.mark.parametrize("bad", [None, "", "abc", "4", "-1", "1.5"])
def test_invalid_or_missing_answer_is_rejected(bad):
    submitted = _all(BEST)
    submitted["alpha-3"] = bad
    with pytest.raises(AssessmentError):
        quiz.score("alpha", submitted)


def test_unknown_field_is_rejected():
    with pytest.raises(AssessmentError):
        quiz.score("no-such-field", {})


def test_missing_role_lists_give_empty_tuples():
    result = quiz.score("beta", {"beta-1": BEST})
    assert result.roles == () and result.freelance == ()


def test_field_listing_and_lookup():
    summaries = quiz.fields()
    assert [s.key for s in summaries] == ["alpha", "beta"]
    assert summaries[0].questions == 4
    assert quiz.names() == {"alpha": "Alpha field", "beta": "Beta field"}
    assert quiz.field("alpha") is FAKE_BANK["alpha"]
    assert quiz.field("nope") is None


def test_result_labels_and_level_scale():
    result = quiz.score("alpha", _all(TWO_POINTS))       # 8/12 = 67% -> intermediate
    assert result.level == "intermediate" and result.level_label == "Intermediate"
    assert [state for _, state in result.scale] == ["past", "past", "current", ""]


# ── The real question bank must match the shape the scoring code expects ──

def test_real_bank_structure():
    assert len(REAL_BANK) >= 1
    seen_ids = set()
    for key, field in REAL_BANK.items():
        assert field["name"] and field["blurb"]
        assert set(field["roles"]) == set(LEVELS) and set(field["freelance"]) == set(LEVELS)
        for q in field["questions"]:
            assert q["id"] not in seen_ids and q["id"].startswith(key + "-")
            seen_ids.add(q["id"])
            points = [o["points"] for o in q["options"]]
            assert len(points) == 4 and points.count(3) == 1 and set(points) <= {0, 1, 2, 3}


def test_every_real_field_scores_from_none_to_advanced():
    real = Questionnaire(REAL_BANK)
    for key, field in REAL_BANK.items():
        best = {q["id"]: [o["points"] for o in q["options"]].index(3) for q in field["questions"]}
        worst = {q["id"]: [o["points"] for o in q["options"]].index(0) for q in field["questions"]}
        assert real.score(key, best).level == "advanced"
        assert real.score(key, worst).level == "none"

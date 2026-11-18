"""Timeline planning logic, run against a small fake catalogue."""
from datetime import date

import pytest

from services.timelines import CURRENT, DONE, KNOWN, LOCKED, TimelinePlanner


def _phase(name, level, weeks, steps):
    return {"name": name, "weeks": weeks, "level": level, "title": f"{name} title",
            "summary": f"{name} summary", "tags": ["t1", "t2", "t3"],
            "steps": [{"title": s, "type": "course", "platform": "Other", "skill_tags": "x, y"} for s in steps]}


CATALOGUE = {
    "alpha": {"name": "Alpha field", "phases": [
        _phase("One", "beginner", (2, 4), ["Step A", "Step B"]),
        _phase("Two", "beginner", (3, 3), ["Step C"]),
        _phase("Three", "intermediate", (1, 1), ["Step D", "Step E"]),
        _phase("Four", "advanced", (4, 6), ["Step F"]),
        _phase("Five", "advanced", None, ["Step G", "Step H"]),
    ]},
    "beta": {"name": "Beta field", "phases": [_phase("Only", "beginner", (1, 2), ["Solo"])]},
}
TODAY = date(2026, 10, 1)
planner = TimelinePlanner(CATALOGUE)


def states(view):
    return [p.state for p in view.phases]


def test_new_user_starts_at_phase_one():
    view = planner.plan("alpha", "none", [], TODAY)
    assert states(view) == [CURRENT, LOCKED, LOCKED, LOCKED, LOCKED]
    assert view.current.number == 1 and view.field_name == "Alpha field"


def test_beginner_still_starts_at_phase_one():
    assert planner.plan("alpha", "beginner", [], TODAY).current.number == 1


def test_intermediate_skips_beginner_phases():
    view = planner.plan("alpha", "intermediate", [], TODAY)
    assert states(view) == [KNOWN, KNOWN, CURRENT, LOCKED, LOCKED]


def test_advanced_skips_beginner_and_intermediate_phases():
    view = planner.plan("alpha", "advanced", [], TODAY)
    assert states(view) == [KNOWN, KNOWN, KNOWN, CURRENT, LOCKED]
    assert view.level_label == "Advanced"


def test_completed_steps_finish_a_phase_and_move_current_on():
    items = [{"title": "step a", "status": "completed"},          # title match ignores case
             {"title": "  Step B ", "status": "completed"}]       # ...and spaces
    view = planner.plan("alpha", "none", items, TODAY)
    assert states(view)[:2] == [DONE, CURRENT]


def test_step_statuses_and_counts():
    items = [{"title": "Step A", "status": "completed"}, {"title": "Step B", "status": "in_progress"}]
    phase = planner.plan("alpha", "none", items, TODAY).phases[0]
    assert phase.steps == (("Step A", "done"), ("Step B", "added"))
    assert (phase.added, phase.done) == (2, 1)
    assert phase.state == CURRENT and not phase.can_add       # everything already added


def test_only_the_current_phase_can_be_added():
    view = planner.plan("alpha", "none", [], TODAY)
    assert [p.can_add for p in view.phases] == [True, False, False, False, False]


def test_a_finished_later_phase_shows_done_even_after_current():
    items = [{"title": "Step C", "status": "completed"}]
    assert states(planner.plan("alpha", "none", items, TODAY))[:3] == [CURRENT, DONE, LOCKED]


def test_dates_chain_from_today_using_the_longest_estimate():
    view = planner.plan("alpha", "none", [], TODAY)
    one, two, three, four, five = view.phases
    assert (one.starts, one.ends) == (date(2026, 10, 1), date(2026, 10, 29))     # 4 weeks
    assert (two.starts, two.ends) == (date(2026, 10, 29), date(2026, 11, 19))    # 3 weeks
    assert three.starts == date(2026, 11, 19) and five.ends is None              # ongoing


def test_known_and_done_phases_have_no_dates():
    view = planner.plan("alpha", "intermediate", [], TODAY)
    assert view.phases[0].starts is None and view.phases[2].starts == TODAY


def test_all_done_means_no_current_phase():
    items = [{"title": t, "status": "completed"} for t in ["Solo"]]
    assert planner.plan("beta", "none", items, TODAY).current is None


@pytest.mark.parametrize("weeks, label", [((2, 4), "2–4 weeks"), ((3, 3), "3 weeks"), ((1, 1), "1 week"), (None, "Ongoing")])
def test_duration_labels(weeks, label):
    cat = {"f": {"name": "F", "phases": [_phase("P", "beginner", weeks, ["S"])]}}
    assert TimelinePlanner(cat).plan("f", "none", [], TODAY).phases[0].duration == label


def test_items_for_phase_maps_steps_to_roadmap_fields():
    items = planner.items_for_phase("alpha", 3)
    assert [i["title"] for i in items] == ["Step D", "Step E"]
    assert items[0]["difficulty"] == "intermediate" and items[0]["priority"] == 3
    assert planner.items_for_phase("alpha", 1)[0]["priority"] == 5
    assert planner.items_for_phase("alpha", 5)[0]["priority"] == 1


@pytest.mark.parametrize("number", [0, 6, -1])
def test_items_for_unknown_phase_raise(number):
    with pytest.raises(IndexError):
        planner.items_for_phase("alpha", number)


def test_field_listing_and_validation():
    assert planner.fields() == [("alpha", "Alpha field"), ("beta", "Beta field")]
    assert planner.is_valid("alpha", "beginner")
    assert not planner.is_valid("alpha", "expert") and not planner.is_valid("nope", "none")


def test_date_range_labels():
    one, two, three, four, five = planner.plan("alpha", "none", [], TODAY).phases
    assert one.date_range == "Oct 1 – Oct 29"
    assert five.date_range.startswith("From ")
    assert planner.plan("alpha", "intermediate", [], TODAY).phases[0].date_range == ""


def test_step_rows_carry_readable_labels():
    items = [{"title": "Step A", "status": "completed"}]
    rows = planner.plan("alpha", "none", items, TODAY).phases[0].step_rows
    assert rows == (("Step A", "done", "done"), ("Step B", "missing", "not added yet"))

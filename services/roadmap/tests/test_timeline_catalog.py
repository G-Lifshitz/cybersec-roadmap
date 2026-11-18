"""The real timeline catalogue must match the shape TimelinePlanner expects.

Checks structure only (counts, allowed values, ordering), never the wording.
"""
from datetime import date

from services.assessment import LEVELS
from services.question_bank import FIELDS
from services.timeline_catalog import TRACKS
from services.timelines import TimelinePlanner

PHASE_LEVELS = ("beginner", "intermediate", "advanced")
# Must match ITEM_TYPES / PLATFORMS in app.py, because steps become roadmap items.
ITEM_TYPES = {"course", "cert", "lab", "book", "project"}
PLATFORMS = {"HTB", "THM", "YouTube", "Coursera", "OffSec", "TCM", "Other"}


def test_same_fields_as_the_questionnaire():
    assert list(TRACKS) == list(FIELDS)


def test_every_track_has_five_ordered_phases():
    for key, track in TRACKS.items():
        phases = track["phases"]
        assert track["name"] and len(phases) == 5, key
        ranks = [PHASE_LEVELS.index(p["level"]) for p in phases]
        assert ranks == sorted(ranks), key                       # level never goes down
        assert phases[0]["level"] == "beginner" and phases[-1]["level"] == "advanced", key


def test_phase_fields_are_well_formed():
    for key, track in TRACKS.items():
        for i, phase in enumerate(track["phases"]):
            assert phase["name"] and phase["title"] and phase["summary"], key
            assert 3 <= len(phase["tags"]) <= 4, key
            weeks = phase["weeks"]
            if weeks is None:
                assert i == len(track["phases"]) - 1, f"{key}: only the last phase may be ongoing"
            else:
                low, high = weeks
                assert 1 <= low <= high <= 16, key


def test_steps_can_become_roadmap_items():
    for key, track in TRACKS.items():
        titles = []
        for phase in track["phases"]:
            assert 2 <= len(phase["steps"]) <= 3, key
            for step in phase["steps"]:
                assert step["type"] in ITEM_TYPES and step["platform"] in PLATFORMS, (key, step["type"], step["platform"])
                assert step["skill_tags"] == step["skill_tags"].lower(), key
                titles.append(step["title"].strip().lower())
        assert len(titles) == len(set(titles)), f"{key}: duplicate step titles"


def test_every_track_plans_at_every_level():
    planner = TimelinePlanner(TRACKS)
    for key in TRACKS:
        for level in LEVELS:
            view = planner.plan(key, level, [], date(2026, 10, 1))
            assert len(view.phases) == 5

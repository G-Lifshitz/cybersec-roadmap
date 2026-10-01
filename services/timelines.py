"""Career timeline: lays a field's learning phases out against the user's own roadmap.

The phases are data (services/timeline_catalog.py). Like the questionnaire,
this module only knows the shape of that data and receives it through the
constructor, so the tests run against a small fake catalogue.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from services.assessment import LEVEL_LABELS, LEVELS

# What a phase looks like for this user.
KNOWN = "known"        # below the user's level: assumed covered
DONE = "done"          # every step is on their roadmap and completed
CURRENT = "current"    # the first phase still to finish
LOCKED = "locked"      # comes after the current phase

STEP_LABELS = {"done": "done", "added": "on your roadmap", "missing": "not added yet"}


@dataclass(frozen=True)
class PhaseView:
    number: int
    name: str
    title: str
    summary: str
    tags: tuple
    level: str
    weeks: Optional[tuple]      # (min, max) or None for an ongoing phase
    state: str
    steps: tuple                # ((title, "done" | "added" | "missing"), ...)
    starts: Optional[date]      # estimates, only for the current and later phases
    ends: Optional[date]

    @property
    def duration(self):
        if self.weeks is None:
            return "Ongoing"
        low, high = self.weeks
        return f"{low} week{'s' if high != 1 else ''}" if low == high else f"{low}–{high} weeks"

    @property
    def date_range(self):
        """'Oct 1 – Oct 29', 'From Nov 19' for an ongoing phase, '' when there's no estimate."""
        if self.starts is None:
            return ""
        if self.ends is None:
            return f"From {_short(self.starts)}"
        return f"{_short(self.starts)} – {_short(self.ends)}"

    @property
    def step_rows(self):
        """((title, status, label), ...) for the current-phase checklist."""
        return tuple((title, status, STEP_LABELS[status]) for title, status in self.steps)

    @property
    def added(self):
        return sum(1 for _, status in self.steps if status != "missing")

    @property
    def done(self):
        return sum(1 for _, status in self.steps if status == "done")

    @property
    def can_add(self):
        """Only the current phase offers 'add to my roadmap', and only while something is missing."""
        return self.state == CURRENT and self.added < len(self.steps)


@dataclass(frozen=True)
class TimelineView:
    field: str
    field_name: str
    level: str
    phases: tuple

    @property
    def level_label(self):
        return LEVEL_LABELS[self.level]

    @property
    def current(self):
        return next((p for p in self.phases if p.state == CURRENT), None)


class TimelinePlanner:
    """catalogue: {field_key: {"name": str, "phases": [phase dict, ...]}}"""

    def __init__(self, catalogue):
        self._tracks = catalogue

    def fields(self):
        """[(key, name)] in catalogue order, for the path picker."""
        return [(key, track["name"]) for key, track in self._tracks.items()]

    def is_valid(self, field, level):
        return field in self._tracks and level in LEVELS

    def plan(self, field, level, items, today):
        """Work out every phase's state, step statuses and estimated dates.

        items: the user's roadmap rows (anything with "title" and "status").
        Steps are matched to items by title, ignoring case and surrounding spaces.
        today: passed in rather than read from the clock, so tests are repeatable.
        """
        track = self._tracks[field]
        status_by_title = {_key(item["title"]): item["status"] for item in items}
        user_rank = LEVELS.index(level)

        phases, have_current, cursor = [], False, today
        for number, phase in enumerate(track["phases"], start=1):
            steps = tuple((s["title"], _step_status(status_by_title.get(_key(s["title"]))))
                          for s in phase["steps"])
            complete = all(status == "done" for _, status in steps)

            if LEVELS.index(phase["level"]) < user_rank:
                state = KNOWN
            elif complete:
                state = DONE
            elif not have_current:
                state, have_current = CURRENT, True
            else:
                state = LOCKED

            starts = ends = None
            if state in (CURRENT, LOCKED):
                starts = cursor
                if phase["weeks"] is not None:
                    ends = cursor + timedelta(weeks=phase["weeks"][1])
                    cursor = ends

            phases.append(PhaseView(
                number=number, name=phase["name"], title=phase["title"],
                summary=phase["summary"], tags=tuple(phase["tags"]), level=phase["level"],
                weeks=phase["weeks"], state=state, steps=steps, starts=starts, ends=ends,
            ))
        return TimelineView(field, track["name"], level, tuple(phases))

    def items_for_phase(self, field, number):
        """The phase's steps as roadmap-item fields, ready for roadmap.create_many().

        Earlier phases get a higher priority (phase 1 -> 5, phase 5 -> 1), and the
        phase's level becomes the item difficulty. Raises KeyError/IndexError for
        an unknown field or phase number.
        """
        phases = self._tracks[field]["phases"]
        if not 1 <= number <= len(phases):
            raise IndexError(number)
        phase = phases[number - 1]
        return [
            {
                "title": step["title"], "type": step["type"], "platform": step["platform"],
                "url": "", "skill_tags": step["skill_tags"],
                "difficulty": phase["level"], "priority": max(1, 6 - number),
            }
            for step in phase["steps"]
        ]


def _short(day):
    return f"{day:%b} {day.day}"     # "Oct 1" on every OS (no %-d)


def _key(title):
    return (title or "").strip().lower()


def _step_status(item_status):
    if item_status is None:
        return "missing"
    return "done" if item_status == "completed" else "added"

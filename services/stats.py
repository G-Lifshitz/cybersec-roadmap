"""Study statistics: streaks, a month calendar and weekly / per-skill totals.

Everything here works on plain data, with no database and no clock: the route
reads the user's log entries once and passes them in together with today's
date, so every rule is unit-tested with fixed dates.
"""
import calendar
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from models.roadmap import split_tags

# Calendar shading by minutes studied that day: (minimum minutes, shade 1-4),
# checked from the top down. Changing the scale is a data change.
SHADE_LEVELS = ((120, 4), (60, 3), (30, 2), (1, 1))
WEEKS_SHOWN = 12
TOP_SKILLS = 8
WEEKDAYS = tuple(calendar.day_abbr[i] for i in range(7))   # Mon ... Sun
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


@dataclass(frozen=True)
class Entry:
    day: date
    minutes: int
    tags: tuple


@dataclass(frozen=True)
class CalendarDay:
    day: date
    minutes: int
    shade: int        # 0 = nothing logged ... 4 = two hours or more
    in_month: bool    # False for the padding days from the months either side
    is_today: bool

    @property
    def title(self):
        return f"{short_date(self.day)}: {duration(self.minutes) if self.minutes else 'no study logged'}"


@dataclass(frozen=True)
class Bar:
    label: str
    value: int
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self):
        return round(self.x + self.width / 2, 2)


@dataclass(frozen=True)
class StatsReport:
    total_minutes: int
    sessions: int
    days_studied: int
    current_streak: int
    longest_streak: int
    month_label: str
    month_grid: list
    prev_month: str
    next_month: Optional[str]   # None while showing the current month (no future months)
    weekly: list                # [Bar]
    skills: list                # [(tag, minutes, percent of the top skill)]
    weekdays: tuple = WEEKDAYS

    @property
    def total_hours(self):
        return round(self.total_minutes / 60, 1)


# ── Small helpers ──────────────────────────────────────────────────────────

def duration(minutes):
    """90 -> '1h 30m', 45 -> '45m', 120 -> '2h'. Also registered as the Jinja filter `duration`."""
    minutes = int(minutes or 0)
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    return f"{hours}h" if hours else f"{rest}m"


def short_date(day):
    return f"{day:%b} {day.day}"     # "Oct 2" on every OS (no %-d)


def to_entries(rows):
    """Model rows (day 'YYYY-MM-DD', minutes, skill_tags) -> Entry objects."""
    return [
        Entry(date.fromisoformat(row["day"]), int(row["minutes"] or 0), tuple(split_tags(row["skill_tags"])))
        for row in rows
    ]


def shade_for(minutes):
    for minimum, shade in SHADE_LEVELS:
        if minutes >= minimum:
            return shade
    return 0


# ── The calculations ───────────────────────────────────────────────────────

def daily_minutes(entries):
    """{date: total minutes that day}."""
    totals = defaultdict(int)
    for entry in entries:
        totals[entry.day] += entry.minutes
    return dict(totals)


def current_streak(days, today):
    """Consecutive study days up to today.

    If nothing is logged today yet, the streak counts back from yesterday, so
    it doesn't drop to 0 every morning before you've had a chance to study.
    """
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def longest_streak(days):
    best = run = 0
    previous = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day
    return best


def week_start(day):
    return day - timedelta(days=day.weekday())      # weeks start on Monday


def weekly_minutes(daily, today, weeks=WEEKS_SHOWN):
    """[(monday, minutes)] for the last `weeks` weeks, oldest first, empty weeks included."""
    this_week = week_start(today)
    starts = [this_week - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    totals = defaultdict(int)
    for day, minutes in daily.items():
        totals[week_start(day)] += minutes
    return [(start, totals.get(start, 0)) for start in starts]


def minutes_by_skill(entries, top=TOP_SKILLS):
    """[(tag, minutes)] most-studied first. A log on an item with two tags counts toward both."""
    totals = defaultdict(int)
    for entry in entries:
        for tag in entry.tags:
            totals[tag] += entry.minutes
    ranked = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    return [pair for pair in ranked if pair[1] > 0][:top]


def month_grid(year, month, daily, today):
    """The month as weeks of 7 CalendarDays (Monday first), padded with days from the months either side."""
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    return [
        [CalendarDay(d, daily.get(d, 0), shade_for(daily.get(d, 0)), d.month == month, d == today) for d in week]
        for week in weeks
    ]


def parse_month(raw, today):
    """'2026-09' -> (2026, 9). Anything malformed, or a month in the future, gives today's month."""
    match = _MONTH_RE.match(raw or "")
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12 and year >= 2000 and (year, month) <= (today.year, today.month):
            return year, month
    return today.year, today.month


def shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def bar_chart(points, width=900, height=150, gap=10):
    """Bar geometry for an inline SVG, scaled to the tallest bar.

    The template only draws the rectangles; every coordinate is worked out here.
    """
    if not points:
        return []
    peak = max(value for _, value in points) or 1
    slot = width / len(points)
    bar_width = max(1.0, slot - gap)
    bars = []
    for i, (label, value) in enumerate(points):
        bar_height = height * value / peak
        bars.append(Bar(label, value, round(i * slot + gap / 2, 2), round(height - bar_height, 2),
                        round(bar_width, 2), round(bar_height, 2)))
    return bars


def build_report(entries, today, year, month):
    """Everything the stats page shows, for one user and one calendar month."""
    daily = daily_minutes(entries)
    days = {entry.day for entry in entries}
    skills = minutes_by_skill(entries)
    top = skills[0][1] if skills else 0
    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    return StatsReport(
        total_minutes=sum(daily.values()),
        sessions=len(entries),
        days_studied=len(days),
        current_streak=current_streak(days, today),
        longest_streak=longest_streak(days),
        month_label=f"{calendar.month_name[month]} {year}",
        month_grid=month_grid(year, month, daily, today),
        prev_month=f"{prev_year:04d}-{prev_month:02d}",
        next_month=None if (next_year, next_month) > (today.year, today.month) else f"{next_year:04d}-{next_month:02d}",
        weekly=bar_chart([(short_date(start), minutes) for start, minutes in weekly_minutes(daily, today)]),
        skills=[(tag, minutes, round(100 * minutes / top)) for tag, minutes in skills],
    )

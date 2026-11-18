"""Stats maths: pure functions, fixed dates, no database."""
from datetime import date, timedelta

import pytest

import services.stats as stats
from services.stats import Entry

TODAY = date(2026, 10, 2)          # a Friday


def d(offset):
    """TODAY + offset days."""
    return TODAY + timedelta(days=offset)


def test_duration_labels():
    assert [stats.duration(m) for m in (0, 45, 60, 90, 125, None)] == ["0m", "45m", "1h", "1h 30m", "2h 5m", "0m"]


def test_to_entries_parses_rows_and_splits_tags():
    rows = [{"day": "2026-10-01", "minutes": 30, "skill_tags": "Web, network"},
            {"day": "2026-10-02", "minutes": None, "skill_tags": None}]
    assert stats.to_entries(rows) == [Entry(date(2026, 10, 1), 30, ("web", "network")),
                                      Entry(date(2026, 10, 2), 0, ())]


def test_daily_minutes_adds_up_each_day():
    entries = [Entry(d(0), 30, ()), Entry(d(0), 15, ()), Entry(d(-1), 60, ())]
    assert stats.daily_minutes(entries) == {d(0): 45, d(-1): 60}


@pytest.mark.parametrize("days, expected", [
    (set(), 0),
    ({d(0)}, 1),
    ({d(0), d(-1), d(-2)}, 3),
    ({d(-1), d(-2)}, 2),           # nothing today yet: streak still counts up to yesterday
    ({d(-2), d(-3)}, 0),           # missed yesterday: streak broken
    ({d(0), d(-2)}, 1),
])
def test_current_streak(days, expected):
    assert stats.current_streak(days, TODAY) == expected


@pytest.mark.parametrize("days, expected", [
    (set(), 0),
    ({d(0)}, 1),
    ({d(-10), d(-9), d(-8), d(-1), d(0)}, 3),
    ({d(-30), d(-1)}, 1),
])
def test_longest_streak(days, expected):
    assert stats.longest_streak(days) == expected


def test_weeks_start_on_monday():
    assert stats.week_start(TODAY) == date(2026, 9, 28)
    assert stats.week_start(date(2026, 9, 28)) == date(2026, 9, 28)


def test_weekly_minutes_covers_twelve_weeks_oldest_first():
    daily = {d(0): 30, d(-1): 20, d(-7): 60, d(-200): 999}        # the last one is outside the window
    weeks = stats.weekly_minutes(daily, TODAY)
    assert len(weeks) == 12 and weeks[-1] == (date(2026, 9, 28), 50) and weeks[-2] == (date(2026, 9, 21), 60)
    assert weeks[0][0] == date(2026, 7, 13) and sum(m for _, m in weeks) == 110


def test_minutes_by_skill_counts_every_tag_and_ranks():
    entries = [Entry(d(0), 60, ("web", "network")), Entry(d(-1), 30, ("web",)),
               Entry(d(-2), 0, ("linux",)), Entry(d(-3), 10, ())]
    assert stats.minutes_by_skill(entries) == [("web", 90), ("network", 60)]
    assert stats.minutes_by_skill(entries, top=1) == [("web", 90)]


@pytest.mark.parametrize("minutes, shade", [(0, 0), (1, 1), (29, 1), (30, 2), (59, 2), (60, 3), (119, 3), (120, 4), (600, 4)])
def test_shade_levels(minutes, shade):
    assert stats.shade_for(minutes) == shade


def test_month_grid_shape_and_flags():
    grid = stats.month_grid(2026, 10, {TODAY: 45}, TODAY)
    assert all(len(week) == 7 for week in grid)
    assert grid[0][0].day == date(2026, 9, 28) and not grid[0][0].in_month      # padding from September
    today = next(cell for week in grid for cell in week if cell.day == TODAY)
    assert today.is_today and today.minutes == 45 and today.shade == 2
    assert today.title == "Oct 2: 45m"
    assert grid[1][0].title.endswith("no study logged")


@pytest.mark.parametrize("raw, expected", [
    ("2026-09", (2026, 9)), ("2026-10", (2026, 10)),
    ("2026-11", (2026, 10)),          # future month -> current month
    ("2026-13", (2026, 10)), ("1999-05", (2026, 10)), ("abc", (2026, 10)),
    ("", (2026, 10)), (None, (2026, 10)), ("2026-9", (2026, 10)), ("2026-09; DROP", (2026, 10)),
])
def test_parse_month_only_accepts_real_past_months(raw, expected):
    assert stats.parse_month(raw, TODAY) == expected


def test_shift_month_wraps_years():
    assert stats.shift_month(2026, 1, -1) == (2025, 12)
    assert stats.shift_month(2026, 12, 1) == (2027, 1)
    assert stats.shift_month(2026, 10, 0) == (2026, 10)


def test_bar_chart_scales_to_the_tallest_bar():
    bars = stats.bar_chart([("a", 50), ("b", 100), ("c", 0)], width=300, height=100, gap=10)
    assert [b.height for b in bars] == [50.0, 100.0, 0.0]
    assert [b.y for b in bars] == [50.0, 0.0, 100.0]
    assert bars[0].x == 5.0 and bars[0].width == 90.0 and bars[0].center == 50.0


def test_bar_chart_edge_cases():
    assert stats.bar_chart([]) == []
    assert all(b.height == 0 for b in stats.bar_chart([("a", 0), ("b", 0)]))   # no division by zero


def test_build_report_puts_it_all_together():
    entries = [Entry(d(0), 90, ("web",)), Entry(d(-1), 30, ("web", "linux")), Entry(d(-40), 15, ())]
    report = stats.build_report(entries, TODAY, 2026, 10)
    assert (report.total_minutes, report.total_hours, report.sessions, report.days_studied) == (135, 2.2, 3, 3)
    assert (report.current_streak, report.longest_streak) == (2, 2)
    assert report.month_label == "October 2026"
    assert (report.prev_month, report.next_month) == ("2026-09", None)          # no future months
    assert stats.build_report(entries, TODAY, 2026, 8).next_month == "2026-09"
    assert len(report.weekly) == 12 and report.weekly[-1].value == 120
    assert report.skills == [("web", 120, 100), ("linux", 30, 25)]
    assert report.weekdays[0] == "Mon"


def test_empty_report():
    report = stats.build_report([], TODAY, 2026, 10)
    assert report.sessions == 0 and report.current_streak == 0 and report.skills == []
    assert all(b.height == 0 for b in report.weekly)

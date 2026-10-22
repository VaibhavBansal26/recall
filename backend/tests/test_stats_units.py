from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.briefs import spoken_intro, spoken_outro, weakness_score
from app.services.stats import DayStat, compute_streaks, daily_series, window_rate
from app.services.timeutil import day_bounds, local_date

D = date(2030, 6, 10)


def days(*offsets: int) -> set[date]:
    return {D + timedelta(days=o) for o in offsets}


# ---- weakness ----


def test_forgetting_fragility_and_recent_misses_all_make_a_note_weaker() -> None:
    fresh = weakness_score(0.95, False, 0)
    forgotten = weakness_score(0.30, False, 0)
    assert forgotten > fresh
    assert weakness_score(0.95, True, 0) > fresh
    assert weakness_score(0.95, False, 2) > weakness_score(0.95, False, 1) > fresh
    assert weakness_score(None, False, 0) == 0.0  # never reviewed: not "weak", just new


def test_lapses_are_capped_so_one_bad_day_does_not_dominate() -> None:
    assert weakness_score(0.9, False, 4) == weakness_score(0.9, False, 40)


def test_a_fragile_note_outranks_a_merely_old_one_of_similar_strength() -> None:
    assert weakness_score(0.7, True, 0) > weakness_score(0.4, False, 0)


# ---- streaks ----


@pytest.mark.parametrize(
    ("reviewed", "current", "longest"),
    [
        (set(), 0, 0),
        (days(0), 1, 1),  # only today
        (days(-1), 1, 1),  # yesterday: still alive, today is not over
        (days(-2), 0, 1),  # missed yesterday: broken
        (days(-3, -2, -1, 0), 4, 4),
        (days(-5, -4, -3, -1, 0), 2, 3),  # a gap; the longer run is in the past
        (days(-9, -8, -7, -6, -5, 0), 1, 5),
    ],
)
def test_streaks(reviewed: set[date], current: int, longest: int) -> None:
    assert compute_streaks(reviewed, D) == (current, longest)


# ---- daily series ----


def test_series_has_one_entry_per_day_including_empty_ones() -> None:
    by_day = {
        D: DayStat(D, reviews=4, recalled=3, unaided=2),
        D - timedelta(days=2): DayStat(D - timedelta(days=2), 1, 1, 1),
    }
    series = daily_series(by_day, D, 5)
    assert [s.day for s in series] == [D - timedelta(days=n) for n in (4, 3, 2, 1, 0)]
    assert [s.reviews for s in series] == [0, 0, 1, 0, 4]
    assert series[-1].retention == 0.75 and series[0].retention is None


def test_window_rates_weight_by_reviews_not_by_day() -> None:
    series = [
        DayStat(D - timedelta(days=2), 10, 5, 1),
        DayStat(D - timedelta(days=1), 0, 0, 0),
        DayStat(D, 2, 2, 2),
    ]
    assert window_rate(series, 3) == pytest.approx(7 / 12)
    assert window_rate(series, 1) == 1.0
    assert window_rate(series, 3, unaided=True) == pytest.approx(3 / 12)
    assert window_rate([DayStat(D)], 7) is None


# ---- the user's time zone decides what "today" is ----


def test_a_late_evening_in_california_is_already_tomorrow_in_utc() -> None:
    la = ZoneInfo("America/Los_Angeles")
    moment = datetime(2030, 6, 11, 3, 30, tzinfo=UTC)  # 20:30 on the 10th in California
    assert local_date(moment, la) == date(2030, 6, 10)
    assert local_date(moment, ZoneInfo("UTC")) == date(2030, 6, 11)


def test_day_bounds_follow_local_midnights_including_dst_days() -> None:
    la = ZoneInfo("America/Los_Angeles")
    start, end = day_bounds(date(2030, 6, 10), la)
    assert start == datetime(2030, 6, 10, 7, 0, tzinfo=UTC) and end - start == timedelta(hours=24)
    spring_start, spring_end = day_bounds(date(2030, 3, 10), la)  # clocks go forward
    assert spring_end - spring_start == timedelta(hours=23)
    fall_start, fall_end = day_bounds(date(2030, 11, 3), la)  # clocks go back
    assert fall_end - fall_start == timedelta(hours=25)


# ---- spoken wording ----


def test_brief_wording() -> None:
    assert "3 topics that are slipping" in spoken_intro(3)
    assert "one question on each of the topic that is slipping" in spoken_intro(1)
    assert spoken_outro(7) == "And that's your brief. 7 reviews are due today."
    assert "1 review is" in spoken_outro(1)
    assert spoken_outro(0) == "And nothing else is due today."

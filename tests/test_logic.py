"""Rides played back through the commute logic."""

import json
import math
from datetime import datetime, timezone, timedelta

import pytest

from custom_components.commute import logic as L

HOME = (52.2240, 5.1760)      # Hilversum
STATION_H = (52.2257, 5.1813)
STATION_A = (52.3789, 4.9003)  # Amsterdam Centraal
WORK = (52.3676, 4.8870)
S = L.Settings(home=HOME, work=WORK)
TZ = timezone(timedelta(hours=1))
MONDAY = datetime(2026, 11, 16, 8, 0, tzinfo=TZ).timestamp()
SATURDAY = datetime(2026, 11, 21, 10, 0, tzinfo=TZ).timestamp()


def lerp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def ride(trip, t, a, b, kmh, every=120, zone_at_end=None, workday=True, hints=None, s=S, accuracy=30, speed_attr=False):
    """Move from a to b at kmh, a place every `every` seconds. Returns the time at the end."""
    dist = L.distance_m(a, b)
    secs = dist / (kmh / 3.6)
    n = max(1, int(secs // every))
    for i in range(1, n + 1):
        f = i / n
        p = lerp(a, b, f)
        t += secs / n
        fix = L.Fix(p[0], p[1], t, accuracy, (kmh / 3.6) if speed_attr else -1)
        zone = zone_at_end if i == n else None
        trip.update(t, s, zone, fix, workday, hints(t) if callable(hints) else (hints or L.Hints()))
    return t


def at_home(t, workday=True):
    trip = L.Trip()
    trip.update(t, S, "home", L.Fix(HOME[0], HOME[1], t, 10), workday, L.Hints())
    return trip


def test_morning_bike_train_metro_walk():
    t = MONDAY
    trip = at_home(t)
    assert trip.phase == L.HOME
    # Bike to the station.
    t = ride(trip, t, HOME, STATION_H, 16, every=60)
    assert trip.phase == L.MAYBE          # 0.5 km is not yet "clearly to work"
    assert trip.mode == L.CYCLING
    # Wait for the train: standing still keeps the guess.
    t += 240
    trip.update(t, S, None, L.Fix(STATION_H[0], STATION_H[1], t, 30, -1), True, L.Hints())
    assert trip.mode == L.CYCLING and L.WHY_KEPT in trip.why
    # The train.
    t = ride(trip, t, STATION_H, STATION_A, 95, every=180)
    assert trip.phase == L.TO_WORK
    assert trip.mode == L.TRAIN
    assert 80 <= trip.percent() <= 99
    # Metro, then a walk into the work zone.
    mid = lerp(STATION_A, WORK, 0.8)
    t = ride(trip, t, STATION_A, mid, 30, every=30)
    assert trip.mode == L.TRANSIT
    t = ride(trip, t, mid, WORK, 5, every=60, zone_at_end="work")
    assert trip.phase == L.WORK
    assert trip.state == L.NONE
    assert len(trip.durations[L.TO_WORK]) == 1
    modes = [leg[0] for leg in trip.legs]
    # The last few hundred metres on foot are too short to count as a leg with a place every minute.
    assert modes[:3] == [L.CYCLING, L.TRAIN, L.TRANSIT]


def test_evening_cycle_home_direct_with_eta_from_history():
    trip = L.Trip()
    t = MONDAY + 9 * 3600
    trip.update(t, S, "work", L.Fix(WORK[0], WORK[1], t, 10), True, L.Hints())
    trip.durations[L.TO_HOME] = [80 * 60, 76 * 60, 84 * 60]
    start = t
    mid = lerp(WORK, HOME, 0.5)
    t = ride(trip, t, WORK, mid, 20, every=150)
    assert trip.phase == L.TO_HOME
    assert trip.mode == L.CYCLING
    assert 45 <= trip.percent() <= 55
    eta = trip.eta(t, S)
    assert eta is not None and start + 60 * 60 < eta < start + 100 * 60
    t = ride(trip, t, mid, HOME, 20, every=150, zone_at_end="home")
    assert trip.phase == L.HOME
    assert len(trip.durations[L.TO_HOME]) == 4


def test_saturday_is_not_a_commute():
    t = SATURDAY
    trip = at_home(t, workday=False)
    t = ride(trip, t, HOME, lerp(HOME, WORK, 0.5), 20, workday=False)
    assert trip.phase == L.AWAY
    assert not trip.commuting


def test_errand_on_a_work_day_times_out():
    t = MONDAY
    trip = at_home(t)
    shop = (HOME[0] - 0.01, HOME[1] + 0.01)  # the other way
    t = ride(trip, t, HOME, shop, 5)
    assert trip.phase == L.MAYBE and not trip.commuting
    t += L.MAYBE_TIMEOUT_S + 60
    trip.update(t, S, None, None, True, L.Hints())
    assert trip.phase == L.AWAY


def test_going_back_home_cancels():
    t = MONDAY
    trip = at_home(t)
    p = lerp(HOME, WORK, 0.3)
    t = ride(trip, t, HOME, p, 18)
    assert trip.phase == L.TO_WORK
    t = ride(trip, t, p, HOME, 18, zone_at_end="home")
    assert trip.phase == L.HOME
    assert trip.durations[L.TO_WORK] == []


def test_one_odd_speed_does_not_flip_the_guess():
    t = MONDAY
    trip = at_home(t)
    p = lerp(HOME, WORK, 0.3)
    t = ride(trip, t, HOME, p, 18, every=120)
    assert trip.mode == L.CYCLING
    # One place that looks fast (a jump in GPS), then cycling again.
    q = lerp(HOME, WORK, 0.33)
    t += 30
    trip.update(t, S, None, L.Fix(q[0], q[1], t, 30, 40 / 3.6), True, L.Hints())
    assert trip.mode == L.CYCLING
    t = ride(trip, t, q, lerp(HOME, WORK, 0.36), 18)
    assert trip.mode == L.CYCLING


def test_activity_and_ns_tracker_are_strong_hints():
    t = MONDAY
    trip = at_home(t)
    t = ride(trip, t, HOME, lerp(HOME, WORK, 0.2), 30, hints=L.Hints(activity="Cycling"))
    assert trip.mode == L.CYCLING and trip.why == [L.WHY_ACTIVITY]
    t = ride(trip, t, lerp(HOME, WORK, 0.2), lerp(HOME, WORK, 0.25), 30, hints=L.Hints(activity="Automotive", ns_tracker_km=0.4))
    assert trip.mode == L.TRAIN and L.WHY_NS_TRACKER in trip.why


def test_car_when_the_person_drives():
    s = L.Settings(home=HOME, work=WORK, vehicle=L.CAR)
    t = MONDAY
    trip = L.Trip()
    trip.update(t, s, "home", L.Fix(HOME[0], HOME[1], t, 10), True, L.Hints())
    t = ride(trip, t, HOME, lerp(HOME, WORK, 0.6), 90, s=s)
    assert trip.mode == L.CAR


def test_saved_and_restored_through_json():
    t = MONDAY
    trip = at_home(t)
    t = ride(trip, t, HOME, lerp(HOME, WORK, 0.4), 18)
    again = L.Trip.from_dict(json.loads(json.dumps(trip.to_dict())))
    assert again.phase == trip.phase and again.mode == trip.mode and again.trail == trip.trail
    t = ride(again, t, lerp(HOME, WORK, 0.4), lerp(HOME, WORK, 0.5), 18)
    assert again.phase == L.TO_WORK


def test_trail_for_the_screen_is_small_and_starts_at_home():
    t = MONDAY
    trip = at_home(t)
    t = ride(trip, t, HOME, lerp(HOME, WORK, 0.9), 18, every=30)
    flat = trip.trail_for_screen(S)
    assert len(flat) <= L.TRAIL_SEND * 3 and len(flat) % 3 == 0
    assert abs(flat[0]) < 50 and abs(flat[1]) < 50
    assert len(json.dumps(flat)) < 700


def test_ns_trip_now():
    trips = [{"status": "NORMAL", "legs": [{
        "product": {"shortCategoryName": "IC"},
        "origin": {"plannedDateTime": "2026-11-16T17:51:00+0100", "actualDateTime": "2026-11-16T17:54:00+0100"},
        "destination": {"plannedDateTime": "2026-11-16T18:15:00+0100", "actualDateTime": "2026-11-16T18:17:00+0100"},
    }]}]
    now = datetime(2026, 11, 16, 18, 0, tzinfo=TZ).timestamp()
    got = L.ns_trip_now(trips, now)
    assert got["delay"] == 3 and got["label"].startswith("IC ") and got["status"] == "NORMAL"
    assert L.ns_trip_now(trips, now + 3 * 3600) is None
    assert L.ns_trip_now("nonsense", now) is None


@pytest.mark.parametrize("state,want", [("Walking", "walk"), ("on_bicycle", "bike"), ("Automotive", "vehicle"),
                                        ("Stationary", "still"), ("Unknown", None), (None, None)])
def test_activity_names(state, want):
    assert L.normalise_activity(state) == want

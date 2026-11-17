"""The commute logic, free of Home Assistant so it can be tested on its own.

One `Trip` follows one person. Home Assistant feeds it what it knows (a place, the zone the person is in, the iPhone's
activity, the NS train) and asks it what to show: whether a commute is under way, which way, how far, by what, and
why it thinks so.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

# Phases of a person's day.
HOME = "home"            # in the home zone
MAYBE = "maybe"          # left home on a work day, not yet clearly heading for work
TO_WORK = "to_work"      # commuting to work
WORK = "work"            # in the work zone
TO_HOME = "to_home"      # commuting home
AWAY = "away"            # somewhere else, not commuting
COMMUTING = (TO_WORK, TO_HOME)

# Ways of travelling. `transit` is metro, tram and bus together: they cannot be told apart by speed.
WALKING = "walking"
CYCLING = "cycling"
TRAIN = "train"
TRANSIT = "transit"
CAR = "car"
UNKNOWN = "unknown"
NONE = "none"            # the sensor's state when no commute is under way
MODES = [WALKING, CYCLING, TRAIN, TRANSIT, CAR, UNKNOWN]

# Why the guess is what it is (shown by the screen and in Home Assistant).
WHY_SPEED = "speed"
WHY_ACTIVITY = "activity"
WHY_NS_TRACKER = "ns_tracker"
WHY_NS_TRIP = "ns_trip"
WHY_KEPT = "kept"              # standing still or no fresh place: the last guess stays
WHY_VEHICLE = "vehicle_default"

# Thresholds.
CONFIRM_PROGRESS = 0.15        # MAYBE becomes TO_WORK once this much closer to work...
CONFIRM_MIN_KM = 0.3           # ...and at least this many km closer
MAYBE_TIMEOUT_S = 45 * 60      # MAYBE that never got closer is not a commute
GIVE_UP_BACK = 0.25            # a commute that falls this far behind its best progress is over
STILL_TIMEOUT_S = 40 * 60      # a commute that stands still this long outside both zones is over
MOVE_M = 150                   # moved: this far from the last place it stood
TRAIL_STEP_M = 100             # a point on the map at least this far apart
TRAIL_KEEP = 64                # points kept while travelling
TRAIL_SEND = 32                # points sent to the screen
FRESH_S = 10 * 60              # a speed older than this says nothing
HISTORY_KEEP = 10              # commute durations kept per direction
NS_NEAR_KM = 1.5               # the NS tracker this close says "train"


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Metres between two (latitude, longitude) points."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(min(1.0, math.sqrt(h)))


def offset_m(origin: tuple[float, float], p: tuple[float, float]) -> tuple[int, int]:
    """Metres east and north of `origin`, for a small map."""
    north = (p[0] - origin[0]) * 111320.0
    east = (p[1] - origin[1]) * 111320.0 * math.cos(math.radians(origin[0]))
    return round(east), round(north)


def _day(at: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(at).date().isoformat()


@dataclass
class Fix:
    """One place of the person, as Home Assistant has it."""

    lat: float
    lon: float
    at: float                  # seconds since 1970
    accuracy: float = 50.0     # metres
    speed: float | None = None  # metres per second, when the phone says it (iOS says -1 when it does not know)

    @property
    def point(self) -> tuple[float, float]:
        return (self.lat, self.lon)


@dataclass
class Hints:
    """What else is known right now."""

    activity: str | None = None        # the phone's activity sensor, as its state
    ns_tracker_km: float | None = None  # how far the NS train tracker is from the person
    ns_trip: dict[str, Any] | None = None  # the NS train of this direction under way now (see `ns_trip_now`)


@dataclass
class Settings:
    home: tuple[float, float]
    work: tuple[float, float]
    vehicle: str = TRANSIT     # what a vehicle on the road is: TRANSIT or CAR


def normalise_activity(state: str | None) -> str | None:
    """iOS (Walking, Cycling, Automotive, Stationary, Running) and Android (on_foot, on_bicycle, in_vehicle, still)."""
    if not state:
        return None
    s = state.strip().lower()
    if s in ("walking", "running", "on_foot"):
        return "walk"
    if s in ("cycling", "on_bicycle"):
        return "bike"
    if s in ("automotive", "in_vehicle"):
        return "vehicle"
    if s in ("stationary", "still"):
        return "still"
    return None


def classify(speed_kmh: float | None, hints: Hints, vehicle: str) -> tuple[str | None, bool, list[str]]:
    """A guess of the way of travelling: (mode or None to keep the last one, strong, why)."""
    act = normalise_activity(hints.activity)
    ns_active = hints.ns_trip is not None
    if hints.ns_tracker_km is not None and hints.ns_tracker_km <= NS_NEAR_KM and (speed_kmh is None or speed_kmh >= 20):
        return TRAIN, True, [WHY_NS_TRACKER] + ([WHY_SPEED] if speed_kmh is not None else [])
    if act == "bike" and (speed_kmh is None or speed_kmh < 45):
        return CYCLING, True, [WHY_ACTIVITY]
    if act == "walk" and (speed_kmh is None or speed_kmh < 10):
        return WALKING, True, [WHY_ACTIVITY]
    if speed_kmh is None:
        if act == "vehicle":
            return (TRAIN, False, [WHY_ACTIVITY, WHY_NS_TRIP]) if ns_active else (vehicle, False, [WHY_ACTIVITY, WHY_VEHICLE])
        return None, False, [WHY_KEPT]
    if speed_kmh < 1.5:
        return None, False, [WHY_KEPT]
    if speed_kmh < 7:
        return WALKING, False, [WHY_SPEED]
    if speed_kmh < 25:
        if act == "vehicle":
            return vehicle, False, [WHY_SPEED, WHY_ACTIVITY]
        return CYCLING, False, [WHY_SPEED]
    if speed_kmh < 60:
        if ns_active:
            return TRAIN, False, [WHY_SPEED, WHY_NS_TRIP]
        return vehicle, False, [WHY_SPEED, WHY_VEHICLE]
    if ns_active:
        return TRAIN, False, [WHY_SPEED, WHY_NS_TRIP]
    return (TRAIN if vehicle == TRANSIT else CAR), False, [WHY_SPEED]


def _iso_epoch(value: Any) -> float | None:
    from datetime import datetime

    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    # NS writes "2026-05-09T14:05:00+0200"; Python wants "+02:00".
    if len(v) > 5 and v[-5] in "+-" and v[-3] != ":":
        v = v[:-2] + ":" + v[-2:]
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.timestamp()


def ns_trip_now(trips: Any, now: float) -> dict[str, Any] | None:
    """The train leg under way now (or about to leave) in the `trips` of an NS Reisadvies route sensor.

    Returns {"label": "IC 17:51", "delay": 3, "status": "NORMAL", "cancelled": False, "arrive": epoch} or None.
    """
    if not isinstance(trips, list):
        return None
    best = None
    for trip in trips:
        if not isinstance(trip, dict):
            continue
        for leg in trip.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            origin = leg.get("origin") or {}
            dest = leg.get("destination") or {}
            dep_plan = _iso_epoch(origin.get("plannedDateTime"))
            dep = _iso_epoch(origin.get("actualDateTime")) or dep_plan
            arr_plan = _iso_epoch(dest.get("plannedDateTime"))
            arr = _iso_epoch(dest.get("actualDateTime")) or arr_plan
            if dep is None or arr is None:
                continue
            if not (dep - 10 * 60 <= now <= arr + 5 * 60):
                continue
            product = leg.get("product") or {}
            kind = product.get("shortCategoryName") or product.get("categoryCode") or ""
            delays = [round((a - p) / 60) for a, p in ((dep, dep_plan), (arr, arr_plan)) if a and p]
            from datetime import datetime

            local = datetime.fromtimestamp(dep_plan or dep).astimezone()
            item = {
                "label": f"{kind} {local:%H:%M}".strip(),
                "delay": max(delays) if delays else 0,
                "status": trip.get("status"),
                "cancelled": bool(leg.get("cancelled")),
                "arrive": arr,
                "depart": dep,
            }
            if best is None or abs(dep - now) < abs(best["depart"] - now):
                best = item
    return best


@dataclass
class Trip:
    """The state of one person's commuting, kept across restarts with `to_dict` and `from_dict`."""

    phase: str = AWAY
    since: float = 0.0
    start_at: float | None = None
    start_dist_km: float | None = None
    best: float = 0.0
    mode: str = UNKNOWN
    pending: str | None = None
    pending_count: int = 0
    why: list[str] = field(default_factory=list)
    legs: list[list[Any]] = field(default_factory=list)      # [mode, at, progress]
    trail: list[list[float]] = field(default_factory=list)   # [lat, lon, mode index]
    last: list[float] | None = None                          # [lat, lon, at, accuracy]
    speeds: list[list[float]] = field(default_factory=list)  # [at, km/h]
    still_at: list[float] | None = None                      # [lat, lon, since]
    away_dist_km: float | None = None
    durations: dict[str, list[float]] = field(default_factory=lambda: {TO_WORK: [], TO_HOME: []})
    progress: float = 0.0
    speed_kmh: float | None = None
    hints: dict[str, Any] = field(default_factory=dict)
    work_day: str | None = None                              # the last day the person was at work

    # ---- saving ----
    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Trip":
        t = cls()
        for k, v in (data or {}).items():
            if k in cls.__dataclass_fields__:
                setattr(t, k, v)
        return t

    # ---- what it shows ----
    @property
    def commuting(self) -> bool:
        return self.phase in COMMUTING

    @property
    def direction(self) -> str | None:
        if self.phase in (TO_WORK, MAYBE):
            return TO_WORK
        if self.phase == TO_HOME:
            return TO_HOME
        return None

    @property
    def state(self) -> str:
        return self.mode if self.commuting else NONE

    def percent(self) -> int:
        return max(0, min(99, round(self.progress * 100)))

    def eta(self, now: float, s: Settings) -> float | None:
        """When the person is expected at the other end."""
        if not self.commuting or self.start_at is None:
            return None
        elapsed = max(0.0, now - self.start_at)
        history = self.durations.get(self.phase) or []
        by_history = statistics.median(history) if history else None
        by_progress = elapsed / self.progress if self.progress >= 0.2 else None
        if by_history is not None and by_progress is not None:
            w = min(1.0, self.progress)
            total = w * by_progress + (1 - w) * by_history
        elif by_progress is not None:
            total = by_progress
        elif by_history is not None:
            total = by_history
        elif self.speed_kmh and self.speed_kmh > 5:
            remaining = (1 - self.progress) * distance_m(s.home, s.work) / 1000
            total = elapsed + remaining / self.speed_kmh * 3600
        else:
            return None
        eta = max(self.start_at + total, now + 60)
        trip = self.hints.get("ns_trip")
        if self.mode == TRAIN and trip and trip.get("arrive"):
            eta = max(eta, trip["arrive"])
        return eta

    def trail_for_screen(self, s: Settings) -> list[int]:
        """Up to 32 points as one flat list: metres east and north of home, and the mode's index, for each."""
        pts = self.trail
        if len(pts) > TRAIL_SEND:
            step = (len(pts) - 1) / (TRAIL_SEND - 1)
            pts = [pts[round(i * step)] for i in range(TRAIL_SEND)]
        out: list[int] = []
        for lat, lon, m in pts:
            e, n = offset_m(s.home, (lat, lon))
            out += [e, n, int(m)]
        return out

    # ---- what it hears ----
    def update(self, now: float, s: Settings, zone: str | None, fix: Fix | None, workday: bool, hints: Hints) -> None:
        """Take what Home Assistant knows now. `zone` is "home", "work" or None (neither)."""
        self.hints = {"activity": hints.activity, "ns_tracker_km": hints.ns_tracker_km, "ns_trip": hints.ns_trip}
        self._before = list(self.last) if self.last else None
        new_fix = self._take_fix(fix)
        total_km = max(0.05, distance_m(s.home, s.work) / 1000)

        if zone == "home":
            if self.phase == TO_HOME:
                self._finish(now)
            self._enter(HOME, now)
            return
        if zone == "work":
            if self.phase in (TO_WORK, MAYBE):
                self._finish(now)
            self._enter(WORK, now)
            return

        here = fix.point if fix else (tuple(self.last[:2]) if self.last else None)
        if self.phase == HOME:
            if workday:
                self._start(MAYBE, now, s)
            else:
                self._enter(AWAY, now)
        elif self.phase == WORK:
            self._start(TO_HOME, now, s)

        if here is None:
            self._timeouts(now)
            return

        dist_work = distance_m(here, s.work) / 1000
        dist_home = distance_m(here, s.home) / 1000
        if self.phase in (MAYBE, TO_WORK):
            self.progress = max(0.0, 1 - dist_work / total_km)
            raw = 1 - dist_work / total_km
        elif self.phase == TO_HOME:
            self.progress = max(0.0, 1 - dist_home / total_km)
            raw = 1 - dist_home / total_km
        else:
            raw = 0.0

        self._moved(now, here)
        self._guess(now, hints, s, new_fix)

        if self.phase == MAYBE:
            closer = (self.start_dist_km or dist_work) - dist_work
            if raw >= CONFIRM_PROGRESS and closer >= CONFIRM_MIN_KM:
                self.phase = TO_WORK
                self.best = raw
            elif raw < -0.10 or now - (self.start_at or now) > MAYBE_TIMEOUT_S:
                self._enter(AWAY, now)
                self.away_dist_km = dist_work
        elif self.phase in COMMUTING:
            self.best = max(self.best, raw)
            if self.best - raw > GIVE_UP_BACK:
                self._enter(AWAY, now)
                self.away_dist_km = dist_work
        elif self.phase == AWAY and workday and not self._been_to_work_today(now):
            # Someone who went somewhere else first and then heads for work is commuting after all.
            if self.away_dist_km is None:
                self.away_dist_km = dist_work
            elif self.away_dist_km - dist_work >= max(0.25 * total_km, 1.0):
                self._start(TO_WORK, now, s)
                self.progress = max(0.0, 1 - dist_work / total_km)
                self.best = self.progress
        if self.phase in (MAYBE,) + COMMUTING and new_fix and fix is not None:
            self._add_trail(fix)
        self._timeouts(now)

    # ---- inside ----
    def _enter(self, phase: str, now: float) -> None:
        if phase != self.phase:
            self.phase = phase
            self.since = now
        if phase not in (MAYBE,) + COMMUTING:
            self.start_at = None
            self.progress = 0.0
            self.best = 0.0
            self.pending = None
            self.pending_count = 0
        if phase in (HOME, WORK):
            self.away_dist_km = None
        if phase == WORK:
            self.work_day = _day(now)

    def _start(self, phase: str, now: float, s: Settings) -> None:
        self.phase = phase
        self.since = now
        self.start_at = now
        dest = s.work if phase in (MAYBE, TO_WORK) else s.home
        origin = getattr(self, "_before", None) or self.last
        self.start_dist_km = distance_m(tuple(origin[:2]), dest) / 1000 if origin else None
        self.best = 0.0
        self.progress = 0.0
        self.mode = UNKNOWN
        self.pending = None
        self.pending_count = 0
        self.why = []
        self.legs = []
        self.trail = []
        self.still_at = None
        self.speed_kmh = None
        if origin:
            self.trail.append([round(origin[0], 5), round(origin[1], 5), MODES.index(UNKNOWN)])

    def _finish(self, now: float) -> None:
        if self.start_at is None:
            return
        direction = TO_WORK if self.phase in (TO_WORK, MAYBE) else TO_HOME
        minutes = now - self.start_at
        if 60 <= minutes <= 4 * 3600:
            history = self.durations.setdefault(direction, [])
            history.append(minutes)
            del history[:-HISTORY_KEEP]

    def _been_to_work_today(self, now: float) -> bool:
        return self.work_day == _day(now)

    def _take_fix(self, fix: Fix | None) -> bool:
        """Keep a new place and the speed it tells; True when it is a new place."""
        if fix is None:
            return False
        if self.last and abs(fix.at - self.last[2]) < 1 and fix.lat == self.last[0] and fix.lon == self.last[1]:
            return False
        speed = None
        if fix.speed is not None and fix.speed >= 0:
            speed = fix.speed * 3.6
        elif self.last and fix.at - self.last[2] >= 15:
            d = distance_m(fix.point, (self.last[0], self.last[1]))
            noise = (fix.accuracy + self.last[3]) / 2
            speed = 0.0 if d < noise else d / (fix.at - self.last[2]) * 3.6
        if speed is not None:
            self.speeds.append([fix.at, min(speed, 300.0)])
            del self.speeds[:-3]
        self.last = [fix.lat, fix.lon, fix.at, fix.accuracy]
        return True

    def _speed_now(self, now: float) -> float | None:
        fresh = [v for at, v in self.speeds if now - at <= FRESH_S]
        if not fresh:
            return None
        if fresh[-1] < 1.5:
            return fresh[-1]  # standing still now: say so at once, the guess stays
        return statistics.median(fresh[-3:])

    def _moved(self, now: float, here: tuple[float, float]) -> None:
        if self.still_at is None or distance_m(here, (self.still_at[0], self.still_at[1])) > MOVE_M:
            self.still_at = [here[0], here[1], now]

    def _timeouts(self, now: float) -> None:
        if self.phase == MAYBE and self.start_at is not None and now - self.start_at > MAYBE_TIMEOUT_S:
            self._enter(AWAY, now)
        elif self.phase in COMMUTING and self.still_at is not None and now - self.still_at[2] > STILL_TIMEOUT_S:
            self._enter(AWAY, now)

    def _guess(self, now: float, hints: Hints, s: Settings, new_fix: bool) -> None:
        if self.phase not in (MAYBE,) + COMMUTING:
            return
        self.speed_kmh = self._speed_now(now)
        mode, strong, why = classify(self.speed_kmh, hints, s.vehicle)
        if mode is None:
            if self.mode == UNKNOWN:
                self.why = why
            elif WHY_KEPT not in self.why:
                self.why = self.why + [WHY_KEPT]
            return
        if mode == self.mode:
            self.why = why
            self.pending, self.pending_count = None, 0
            return
        if strong or self.mode == UNKNOWN:
            self._switch(mode, why, now)
            return
        if not new_fix:
            return
        if self.pending == mode:
            self.pending_count += 1
        else:
            self.pending, self.pending_count = mode, 1
        if self.pending_count >= 2:
            self._switch(mode, why, now)

    def _switch(self, mode: str, why: list[str], now: float) -> None:
        self.mode = mode
        self.why = why
        self.pending, self.pending_count = None, 0
        self.legs.append([mode, round(now), round(self.progress * 100)])
        del self.legs[:-8]
        if self.trail:
            self.trail[-1][2] = MODES.index(mode) if self.trail[-1][2] == MODES.index(UNKNOWN) else self.trail[-1][2]

    def _add_trail(self, fix: Fix) -> None:
        idx = MODES.index(self.mode)
        if self.trail and distance_m(fix.point, (self.trail[-1][0], self.trail[-1][1])) < TRAIL_STEP_M:
            return
        self.trail.append([round(fix.lat, 5), round(fix.lon, 5), idx])
        if len(self.trail) > TRAIL_KEEP:
            # Thin out: keep where it started and every other point after it, and the newest.
            self.trail = [self.trail[0]] + self.trail[1:-1][1::2] + [self.trail[-1]]

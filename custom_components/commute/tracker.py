"""Feeds one person's commute logic from Home Assistant and keeps it across restarts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import logic as L
from .const import (
    CONF_ACTIVITY,
    CONF_HOME_ZONE,
    CONF_NS_TO_HOME,
    CONF_NS_TO_WORK,
    CONF_NS_TRACKER,
    CONF_PERSON,
    CONF_VEHICLE,
    CONF_WORK_DAYS,
    CONF_WORK_ZONE,
    DAYS,
    DEFAULT_WORK_DAYS,
    DOMAIN,
    SIGNAL_UPDATE,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class CommuteTracker:
    """One person: listens to their place and the hints, runs `logic.Trip`, tells the entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.conf: dict[str, Any] = {**entry.data, **entry.options}
        self.trip = L.Trip()
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[Callable[[], None]] = []
        self.settings: L.Settings | None = None

    @property
    def signal(self) -> str:
        return SIGNAL_UPDATE.format(self.entry.entry_id)

    async def async_start(self) -> None:
        saved = await self._store.async_load()
        self.trip = L.Trip.from_dict(saved)
        watched = [self.conf[CONF_PERSON], self.conf[CONF_HOME_ZONE], self.conf[CONF_WORK_ZONE]]
        for key in (CONF_ACTIVITY, CONF_NS_TO_WORK, CONF_NS_TO_HOME, CONF_NS_TRACKER):
            if self.conf.get(key):
                watched.append(self.conf[key])
        self._unsubs.append(async_track_state_change_event(self.hass, watched, self._changed))
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=1)))
        self.update(from_place=True)

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self.trip.to_dict())

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        self.update(from_place=event.data["entity_id"] == self.conf[CONF_PERSON])

    @callback
    def _tick(self, _now: Any) -> None:
        self.update(from_place=False)

    # ---- reading Home Assistant ----
    def _zone(self, entity_id: str) -> tuple[float, float, float, str] | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        lat, lon = _float(state.attributes.get(ATTR_LATITUDE)), _float(state.attributes.get(ATTR_LONGITUDE))
        if lat is None or lon is None:
            return None
        return lat, lon, _float(state.attributes.get("radius")) or 100.0, state.name

    def _fix(self, person: State) -> L.Fix | None:
        lat, lon = _float(person.attributes.get(ATTR_LATITUDE)), _float(person.attributes.get(ATTR_LONGITUDE))
        if lat is None or lon is None:
            return None
        speed = None
        source = person.attributes.get("source")
        tracker = self.hass.states.get(source) if isinstance(source, str) else None
        if tracker is not None:
            speed = _float(tracker.attributes.get("speed"))
        if speed is None:
            speed = _float(person.attributes.get("speed"))
        accuracy = _float(person.attributes.get("gps_accuracy")) or 50.0
        return L.Fix(lat, lon, person.last_updated.timestamp(), accuracy, speed)

    def _in_zone(self, person: State, zone_id: str, zone: tuple[float, float, float, str], fix: L.Fix | None) -> bool:
        if zone_id == "zone.home" and person.state == STATE_HOME:
            return True
        if person.state == zone[3]:
            return True
        if fix is not None:
            return L.distance_m(fix.point, (zone[0], zone[1])) <= zone[2]
        return False

    def _hints(self, fix: L.Fix | None, now: float) -> L.Hints:
        activity = None
        if self.conf.get(CONF_ACTIVITY):
            s = self.hass.states.get(self.conf[CONF_ACTIVITY])
            if s is not None and s.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                activity = s.state
        ns_km = None
        if self.conf.get(CONF_NS_TRACKER) and fix is not None:
            s = self.hass.states.get(self.conf[CONF_NS_TRACKER])
            if s is not None:
                lat, lon = _float(s.attributes.get(ATTR_LATITUDE)), _float(s.attributes.get(ATTR_LONGITUDE))
                if lat is not None and lon is not None:
                    ns_km = L.distance_m(fix.point, (lat, lon)) / 1000
        ns_trip = None
        route = self.conf.get(CONF_NS_TO_HOME) if self.trip.direction == L.TO_HOME else self.conf.get(CONF_NS_TO_WORK)
        if route:
            s = self.hass.states.get(route)
            if s is not None:
                ns_trip = L.ns_trip_now(s.attributes.get("trips"), now)
        return L.Hints(activity=activity, ns_tracker_km=ns_km, ns_trip=ns_trip)

    # ---- running the logic ----
    @callback
    def update(self, from_place: bool) -> None:
        person = self.hass.states.get(self.conf[CONF_PERSON])
        home = self._zone(self.conf[CONF_HOME_ZONE])
        work = self._zone(self.conf[CONF_WORK_ZONE])
        if person is None or home is None or work is None:
            return
        self.settings = L.Settings(home=(home[0], home[1]), work=(work[0], work[1]),
                                   vehicle=self.conf.get(CONF_VEHICLE, L.TRANSIT))
        now = dt_util.utcnow().timestamp()
        fix = self._fix(person)
        zone = None
        if self._in_zone(person, self.conf[CONF_HOME_ZONE], home, fix):
            zone = "home"
        elif self._in_zone(person, self.conf[CONF_WORK_ZONE], work, fix):
            zone = "work"
        days = self.conf.get(CONF_WORK_DAYS, DEFAULT_WORK_DAYS)
        workday = DAYS[dt_util.now().weekday()] in days
        self.trip.update(now, self.settings, zone, fix if from_place else None, workday, self._hints(fix, now))
        self._store.async_delay_save(self.trip.to_dict, 30)
        async_dispatcher_send(self.hass, self.signal)

    # ---- what the entities show ----
    def attributes(self) -> dict[str, Any]:
        t, s = self.trip, self.settings
        now = dt_util.utcnow().timestamp()
        eta = t.eta(now, s) if s else None
        ns = t.hints.get("ns_trip") or {}
        last_at = t.last[2] if t.last else None
        attrs: dict[str, Any] = {
            "person": self.conf.get("name"),
            "commute_phase": t.phase,
            "direction": t.direction,
            "progress": t.percent() if t.phase in (L.MAYBE,) + L.COMMUTING else None,
            "eta_at": dt_util.utc_from_timestamp(eta).isoformat() if eta else None,
            "started_at": dt_util.utc_from_timestamp(t.start_at).isoformat() if t.start_at else None,
            "speed": round(t.speed_kmh) if t.speed_kmh is not None else None,
            "activity": t.hints.get("activity"),
            "ns_distance": round(t.hints["ns_tracker_km"], 1) if t.hints.get("ns_tracker_km") is not None else None,
            "train": ns.get("label"),
            "delay": ns.get("delay"),
            "ns_status": ns.get("status"),
            "place_at": dt_util.utc_from_timestamp(last_at).isoformat() if last_at else None,
            "basis": list(t.why),
            "leg_modes": [leg[0] for leg in t.legs],
            "leg_from": [leg[2] for leg in t.legs],
            "leg_times": [leg[1] for leg in t.legs],
            "trail": t.trail_for_screen(s) if s and t.trail else [],
            "work_offset": list(L.offset_m(s.home, s.work)) if s else [],
        }
        return attrs

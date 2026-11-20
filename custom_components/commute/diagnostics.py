"""Diagnostics: what a person's commute heard and decided, to find out why a trip was (not) seen.

Download it from Settings → Devices & services → Commute → the person → ⋮ → Download diagnostics. It holds the
settings, the place of home and work, the trip as it stands, the journal (every new place and every decision, newest
last) and the last 36 hours of the person, their phone's tracker and the activity sensor from Home Assistant's history.
`tools/replay.py` plays it back through the logic. It holds where the person was: share it only with whom you trust.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_ACTIVITY, CONF_HOME_ZONE, CONF_NS_TRACKER, CONF_PERSON, CONF_WORK_ZONE

HISTORY_HOURS = 36
KEEP_ATTRIBUTES = ("latitude", "longitude", "gps_accuracy", "speed", "source", "altitude", "vertical_accuracy")


async def _history(hass: HomeAssistant, entity_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    try:
        from homeassistant.components.recorder import get_instance, history
    except ImportError:
        return {}
    if "recorder" not in hass.config.components:
        return {}
    end = dt_util.utcnow() + timedelta(minutes=1)
    start = end - timedelta(hours=HISTORY_HOURS)

    def read() -> dict[str, list[Any]]:
        return history.get_significant_states(hass, start, end, entity_ids, significant_changes_only=False,
                                              minimal_response=False, no_attributes=False)

    states = await get_instance(hass).async_add_executor_job(read)
    out: dict[str, list[dict[str, Any]]] = {}
    for entity_id, rows in states.items():
        out[entity_id] = [{
            "state": row.state,
            "at": round(row.last_updated.timestamp()),
            "attributes": {k: row.attributes.get(k) for k in KEEP_ATTRIBUTES if k in row.attributes},
        } for row in rows if hasattr(row, "attributes")]
    return out


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    tracker = entry.runtime_data
    conf = tracker.conf
    s = tracker.settings
    entities = [conf[CONF_PERSON]]
    person = hass.states.get(conf[CONF_PERSON])
    source = person.attributes.get("source") if person else None
    if isinstance(source, str):
        entities.append(source)
    for key in (CONF_ACTIVITY, CONF_NS_TRACKER):
        if conf.get(key):
            entities.append(conf[key])
    zones = {}
    for key in (CONF_HOME_ZONE, CONF_WORK_ZONE):
        z = hass.states.get(conf[key])
        if z is not None:
            zones[key] = {"entity_id": conf[key], "name": z.name, "latitude": z.attributes.get("latitude"),
                          "longitude": z.attributes.get("longitude"), "radius": z.attributes.get("radius")}
    trip = tracker.trip.to_dict()
    journal = trip.pop("journal", [])
    return {
        "version": 1,
        "now": round(dt_util.utcnow().timestamp()),
        "time_zone": hass.config.time_zone,
        "config": dict(conf),
        "zones": zones,
        "settings": {"home": list(s.home), "work": list(s.work), "vehicle": s.vehicle} if s else None,
        "trip": trip,
        "journal": journal,
        "history": await _history(hass, entities),
    }

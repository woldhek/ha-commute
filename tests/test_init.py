"""The integration in a Home Assistant of tests: a person leaves work and cycles home."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.commute.const import DOMAIN

HOME = (52.2240, 5.1760)
WORK = (52.3676, 4.8870)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def zones(hass):
    hass.states.async_set("zone.home", "0", {"latitude": HOME[0], "longitude": HOME[1], "radius": 100, "friendly_name": "Home"})
    hass.states.async_set("zone.work", "0", {"latitude": WORK[0], "longitude": WORK[1], "radius": 150, "friendly_name": "Work"})


def place(hass, state, p, speed=-1):
    hass.states.async_set("device_tracker.phone", state, {"latitude": p[0], "longitude": p[1], "gps_accuracy": 20, "speed": speed})
    hass.states.async_set("person.anton", state, {"latitude": p[0], "longitude": p[1], "gps_accuracy": 20,
                                                  "source": "device_tracker.phone", "friendly_name": "Anton"})


async def test_commute_home(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-16 16:30:00+00:00")  # a Monday
    zones(hass)
    place(hass, "Work", WORK)
    entry = MockConfigEntry(domain=DOMAIN, title="Anton", unique_id="person.anton", data={
        "name": "Anton", "person": "person.anton", "home_zone": "zone.home", "work_zone": "zone.work",
        "work_days": ["mon", "tue", "wed", "thu", "fri"], "vehicle": "transit"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.anton_commute")
    assert state is not None and state.state == "none"
    assert state.attributes["commute_phase"] == "work"
    assert hass.states.get("binary_sensor.anton_commuting").state == "off"

    for i in range(1, 11):
        freezer.tick(timedelta(minutes=3))
        f = i / 20
        place(hass, "not_home", (WORK[0] + (HOME[0] - WORK[0]) * f, WORK[1] + (HOME[1] - WORK[1]) * f), speed=20 / 3.6)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.anton_commute")
    assert state.state == "cycling"
    assert state.attributes["direction"] == "to_home"
    assert 40 <= state.attributes["progress"] <= 60
    assert state.attributes["basis"] == ["speed"]
    assert len(state.attributes["trail"]) % 3 == 0 and state.attributes["trail"]
    assert hass.states.get("binary_sensor.anton_commuting").state == "on"
    assert hass.states.get("sensor.anton_direction").state == "to_home"
    assert hass.states.get("sensor.anton_progress").state == str(state.attributes["progress"])

    freezer.tick(timedelta(minutes=30))
    place(hass, "home", HOME)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.anton_commute").state == "none"
    assert hass.states.get("sensor.anton_commute").attributes["commute_phase"] == "home"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)

"""Commute: follows a person's trip between home and work, and guesses how they travel."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .tracker import CommuteTracker

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

type CommuteConfigEntry = ConfigEntry[CommuteTracker]


async def async_setup_entry(hass: HomeAssistant, entry: CommuteConfigEntry) -> bool:
    tracker = CommuteTracker(hass, entry)
    entry.runtime_data = tracker
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await tracker.async_start()
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CommuteConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
    return ok


async def _reload(hass: HomeAssistant, entry: CommuteConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)

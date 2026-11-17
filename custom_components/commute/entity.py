"""What every entity of a person shares."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify

from .const import CONF_NAME, DOMAIN
from .tracker import CommuteTracker


class CommuteEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _commute_domain = "sensor"

    def __init__(self, tracker: CommuteTracker, key: str) -> None:
        self.tracker = tracker
        self._attr_translation_key = key
        self._attr_unique_id = f"{tracker.entry.entry_id}_{key}"
        # English entity ids whatever Home Assistant's language: sensor.anton_commute, which the screen looks for.
        person = slugify(tracker.conf.get(CONF_NAME) or tracker.entry.title)
        self.entity_id = f"{self._commute_domain}.{person}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tracker.entry.entry_id)},
            name=tracker.conf.get(CONF_NAME) or tracker.entry.title,
            manufacturer="Commute",
            model="Commute",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self.tracker.signal, self.async_write_ha_state))

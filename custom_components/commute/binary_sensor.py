"""Whether a person is commuting: the one to build automations on."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import CommuteEntity


async def async_setup_entry(hass: HomeAssistant, entry, add: AddEntitiesCallback) -> None:
    add([CommutingSensor(entry.runtime_data)])


class CommutingSensor(CommuteEntity, BinarySensorEntity):
    _attr_icon = "mdi:transit-transfer"
    _commute_domain = "binary_sensor"

    def __init__(self, tracker) -> None:
        super().__init__(tracker, "commuting")

    @property
    def is_on(self) -> bool:
        return self.tracker.trip.commuting

"""The sensors of a person's commute."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import logic as L
from .entity import CommuteEntity

# Large lists for the screen, not for the history database.
BIG = frozenset({"trail", "leg_modes", "leg_from", "leg_times", "work_offset", "basis"})


async def async_setup_entry(hass: HomeAssistant, entry, add: AddEntitiesCallback) -> None:
    t = entry.runtime_data
    add([CommuteSensor(t), ProgressSensor(t), ArrivalSensor(t), DirectionSensor(t), DelaySensor(t)])


class CommuteSensor(CommuteEntity, SensorEntity):
    """The way of travelling while a commute is under way, `none` otherwise; everything else in its attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [L.NONE] + L.MODES
    _unrecorded_attributes = BIG

    def __init__(self, tracker) -> None:
        super().__init__(tracker, "commute")

    @property
    def native_value(self) -> str:
        return self.tracker.trip.state

    @property
    def icon(self) -> str:
        return {L.WALKING: "mdi:walk", L.CYCLING: "mdi:bike", L.TRAIN: "mdi:train", L.TRANSIT: "mdi:subway-variant",
                L.CAR: "mdi:car", L.UNKNOWN: "mdi:help-circle-outline"}.get(self.native_value, "mdi:home-clock-outline")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.tracker.attributes()


class ProgressSensor(CommuteEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:map-marker-path"

    def __init__(self, tracker) -> None:
        super().__init__(tracker, "progress")

    @property
    def native_value(self) -> int | None:
        return self.tracker.trip.percent() if self.tracker.trip.commuting else None


class ArrivalSensor(CommuteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, tracker) -> None:
        super().__init__(tracker, "arrival")

    @property
    def native_value(self) -> datetime | None:
        s = self.tracker.settings
        eta = self.tracker.trip.eta(dt_util.utcnow().timestamp(), s) if s else None
        return dt_util.utc_from_timestamp(eta) if eta else None


class DirectionSensor(CommuteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["none", L.TO_WORK, L.TO_HOME]
    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, tracker) -> None:
        super().__init__(tracker, "direction")

    @property
    def native_value(self) -> str:
        t = self.tracker.trip
        return t.direction if t.commuting else "none"


class DelaySensor(CommuteEntity, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:train-variant"

    def __init__(self, tracker) -> None:
        super().__init__(tracker, "train_delay")

    @property
    def native_value(self) -> int | None:
        trip = self.tracker.trip
        ns = trip.hints.get("ns_trip") if trip.commuting else None
        return ns.get("delay") if ns else None

"""Adding a person, and changing their settings later."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import logic as L
from .const import (
    CONF_ACTIVITY,
    CONF_HOME_ZONE,
    CONF_NAME,
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
)


def _optional(key: str, values: dict[str, Any]) -> vol.Optional:
    value = values.get(key)
    return vol.Optional(key, description={"suggested_value": value}) if value else vol.Optional(key)


def _schema(values: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=values.get(CONF_NAME, ""))] = selector.TextSelector()
        fields[vol.Required(CONF_PERSON, default=values.get(CONF_PERSON, vol.UNDEFINED))] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["person", "device_tracker"]))
    fields[vol.Required(CONF_HOME_ZONE, default=values.get(CONF_HOME_ZONE, "zone.home"))] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="zone"))
    fields[vol.Required(CONF_WORK_ZONE, default=values.get(CONF_WORK_ZONE, vol.UNDEFINED))] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="zone"))
    fields[vol.Required(CONF_WORK_DAYS, default=values.get(CONF_WORK_DAYS, DEFAULT_WORK_DAYS))] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=DAYS, multiple=True, mode=selector.SelectSelectorMode.LIST,
                                      translation_key="work_days"))
    fields[vol.Required(CONF_VEHICLE, default=values.get(CONF_VEHICLE, L.TRANSIT))] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=[L.TRANSIT, L.CAR], mode=selector.SelectSelectorMode.LIST,
                                      translation_key="vehicle"))
    fields[_optional(CONF_ACTIVITY, values)] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    fields[_optional(CONF_NS_TO_WORK, values)] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    fields[_optional(CONF_NS_TO_HOME, values)] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    fields[_optional(CONF_NS_TRACKER, values)] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="device_tracker"))
    return vol.Schema(fields)


def _errors(hass, data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if data.get(CONF_HOME_ZONE) == data.get(CONF_WORK_ZONE):
        errors[CONF_WORK_ZONE] = "same_zone"
    if not data.get(CONF_WORK_DAYS):
        errors[CONF_WORK_DAYS] = "no_days"
    for key in (CONF_HOME_ZONE, CONF_WORK_ZONE):
        state = hass.states.get(data.get(key, ""))
        if state is None or "latitude" not in state.attributes:
            errors[key] = "no_zone"
    return errors


class CommuteConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_PERSON])
            self._abort_if_unique_id_configured()
            errors = _errors(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        values = user_input or {}
        if not values.get(CONF_NAME):
            values = {**values}
        return self.async_show_form(step_id="user", data_schema=_schema(values, True), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CommuteOptionsFlow()


class CommuteOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _errors(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
            current = {**current, **user_input}
        return self.async_show_form(step_id="init", data_schema=_schema(current, False), errors=errors)

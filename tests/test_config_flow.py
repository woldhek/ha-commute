import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.commute.const import DOMAIN

from .test_init import zones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_add_a_person(hass: HomeAssistant) -> None:
    zones(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    data = {"name": "Anton", "person": "person.anton", "home_zone": "zone.home", "work_zone": "zone.home",
            "work_days": ["mon"], "vehicle": "transit"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["errors"] == {"work_zone": "same_zone"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**data, "work_zone": "zone.work"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Anton"

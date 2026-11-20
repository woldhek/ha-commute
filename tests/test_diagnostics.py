"""The diagnostics download holds the history and the journal, and tools/replay.py plays it back."""

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.commute.const import DOMAIN
from custom_components.commute.diagnostics import async_get_config_entry_diagnostics

from .test_init import HOME, WORK, place, zones

async def test_diagnostics_and_replay(recorder_mock, enable_custom_integrations, hass: HomeAssistant, freezer, tmp_path: Path) -> None:
    freezer.move_to("2026-11-16 16:30:00+00:00")
    zones(hass)
    place(hass, "Work", WORK)
    entry = MockConfigEntry(domain=DOMAIN, title="Anton", unique_id="person.anton", data={
        "name": "Anton", "person": "person.anton", "home_zone": "zone.home", "work_zone": "zone.work",
        "work_days": ["mon", "tue", "wed", "thu", "fri"], "vehicle": "transit"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for i in range(1, 21):
        freezer.tick(timedelta(minutes=4))
        f = i / 20
        p = (WORK[0] + (HOME[0] - WORK[0]) * f, WORK[1] + (HOME[1] - WORK[1]) * f)
        place(hass, "home" if i == 20 else "not_home", p, speed=20 / 3.6)
        await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["settings"]["home"] == list(HOME)
    assert [e for e in diag["journal"] if e.get("note") == "left the work zone"]
    assert diag["history"]["person.anton"][-1]["state"] == "home"
    assert "latitude" in diag["history"]["person.anton"][-1]["attributes"]

    path = tmp_path / "diag.json"
    path.write_text(json.dumps({"home_assistant": {}, "data": diag}))
    tool = Path(__file__).resolve().parent.parent / "tools" / "replay.py"
    out = subprocess.run([sys.executable, str(tool), str(path)], capture_output=True, text=True, check=True).stdout
    assert "work -> to_home: left the work zone" in out
    assert "to_home -> home" in out
    journal = subprocess.run([sys.executable, str(tool), str(path), "--journal"], capture_output=True, text=True,
                             check=True).stdout
    assert "left the work zone" in journal

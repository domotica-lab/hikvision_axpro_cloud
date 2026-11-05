"""Test della configurazione guidata e dell'avvio in Home Assistant."""
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.hikvision_axpro_cloud.api import (  # noqa: E402
    HikAxProAuthError,
    HikAxProCloud,
)
from custom_components.hikvision_axpro_cloud.const import DOMAIN  # noqa: E402

API = "custom_components.hikvision_axpro_cloud.api.HikAxProCloud"
USER = {"account": "me@example.com", "password": "pw"}
P1 = {"serial": "Q1", "name": "Casa", "model": "DS-PWA96-M-WE", "firmware": "V1"}
P2 = {"serial": "Q2", "name": "Ufficio", "model": "DS-PWA64-L-WE", "firmware": "V1"}
STATUS = {
    "areas": {1: {"name": "Area 1", "state": "disarmed", "alarm": False}},
    "host": {"battery_percent": 90, "ac_connect": True, "cloud_status": "normal"},
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def cloud():
    with patch(f"{API}.list_panels", AsyncMock(return_value=[P1])) as lp, \
         patch(f"{API}.ensure_ready", AsyncMock()), \
         patch(f"{API}.get_full_status", AsyncMock(return_value=STATUS)), \
         patch(f"{API}.device_name", "Casa"):
        yield lp


async def test_single_panel(hass, cloud):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], USER)
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["result"].unique_id == "Q1"
    assert r["data"]["serial"] == "Q1" and len(r["data"]["feature_code"]) == 32


async def test_multiple_panels_choose_one(hass, cloud):
    cloud.return_value = [P1, P2]
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], USER)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "select_panel"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"serial": "Q2"})
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["result"].unique_id == "Q2"


async def test_second_panel_offered_when_first_configured(hass, cloud):
    cloud.return_value = [P1, P2]
    MockConfigEntry(domain=DOMAIN, unique_id="Q1", data={}).add_to_hass(hass)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], USER)
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["result"].unique_id == "Q2"


async def test_wrong_password(hass, cloud):
    cloud.side_effect = HikAxProAuthError("no")
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], USER)
    assert r["errors"] == {"base": "invalid_auth"}


async def test_no_devices(hass, cloud):
    cloud.return_value = []
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], USER)
    assert r["errors"] == {"base": "no_panels"}


async def test_setup_old_entry_gets_feature_code_and_entities(hass, cloud):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="Q1",
                            data={**USER, "serial": "Q1"}, options={"code": "1234"})
    entry.add_to_hass(hass)
    with patch(f"{API}.serial", "Q1"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert len(entry.data["feature_code"]) == 32
    alarm = [s for s in hass.states.async_all("alarm_control_panel")]
    assert len(alarm) == 1 and alarm[0].state == "disarmed"
    assert alarm[0].attributes["code_arm_required"] is False
    assert alarm[0].attributes["supported_features"] == 2  # solo ARM_AWAY
    assert hass.states.async_all("sensor") and hass.states.async_all("binary_sensor")


async def test_options_enable_arm_home(hass, cloud):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="Q1",
                            data={**USER, "serial": "Q1", "feature_code": "f" * 32})
    entry.add_to_hass(hass)
    with patch(f"{API}.serial", "Q1"):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        r = await hass.config_entries.options.async_init(entry.entry_id)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"scan_interval": 30, "code": "", "arm_home": True})
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.CREATE_ENTRY
    alarm = hass.states.async_all("alarm_control_panel")[0]
    assert alarm.attributes["supported_features"] == 3  # ARM_HOME | ARM_AWAY

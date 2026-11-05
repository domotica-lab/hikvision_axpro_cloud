"""Integrazione Hikvision AX PRO via cloud Hik-Connect."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HikAxProAuthError, HikAxProCloud, HikAxProError, new_feature_code
from .const import CONF_ACCOUNT, CONF_FEATURE_CODE, CONF_PASSWORD, CONF_SERIAL, DOMAIN
from .coordinator import HikAxProCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura l'integrazione da una voce di configurazione."""
    if not entry.data.get(CONF_FEATURE_CODE):
        # installazioni precedenti alla 1.2: un identificativo client proprio
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_FEATURE_CODE: new_feature_code()}
        )
    session = async_get_clientsession(hass)
    client = HikAxProCloud(
        account=entry.data[CONF_ACCOUNT],
        password=entry.data[CONF_PASSWORD],
        session=session,
        serial=entry.data.get(CONF_SERIAL),
        feature_code=entry.data[CONF_FEATURE_CODE],
    )

    try:
        await client.ensure_ready()
    except HikAxProAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except HikAxProError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = HikAxProCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Rimuove l'integrazione."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

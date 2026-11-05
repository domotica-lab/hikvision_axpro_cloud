"""Coordinatore: interroga periodicamente lo stato completo della centrale."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HikAxProAuthError, HikAxProCloud, HikAxProError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HikAxProCoordinator(DataUpdateCoordinator):
    """Tiene aggiornato lo stato (aree + diagnostica) della centrale."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HikAxProCloud) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict:
        try:
            return await self.client.get_full_status()
        except HikAxProAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HikAxProError as err:
            raise UpdateFailed(str(err)) from err

"""Diagnostica scaricabile (dati sensibili oscurati)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ACCOUNT, CONF_FEATURE_CODE, CONF_PASSWORD, DOMAIN
from .coordinator import HikAxProCoordinator

TO_REDACT = {CONF_ACCOUNT, CONF_PASSWORD, CONF_FEATURE_CODE, "sim_operator", "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: HikAxProCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": async_redact_data(entry.data, TO_REDACT),
        "firmware": coordinator.client.firmware,
        "model": coordinator.client.model,
        "options": async_redact_data(dict(entry.options), {"code"}),
        "data": async_redact_data(coordinator.data or {}, TO_REDACT),
    }

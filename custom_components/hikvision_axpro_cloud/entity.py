"""Base comune per le entità: device_info condiviso."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HikAxProCoordinator


class HikAxProEntity(CoordinatorEntity[HikAxProCoordinator]):
    """Entità collegata al dispositivo centrale AX PRO."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HikAxProCoordinator) -> None:
        super().__init__(coordinator)
        client = coordinator.client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, client.serial)},
            name=client.device_name or "AX PRO",
            manufacturer=MANUFACTURER,
            model=client.model or MODEL,
            sw_version=client.firmware,
        )

    @property
    def _host(self) -> dict | None:
        return (self.coordinator.data or {}).get("host")

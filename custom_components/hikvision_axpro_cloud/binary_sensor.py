"""Sensori binari della centrale (alimentazione, manomissione, cloud, allarme)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HikAxProCoordinator
from .entity import HikAxProEntity


@dataclass(frozen=True, kw_only=True)
class HikBinaryDescription(BinarySensorEntityDescription):
    """Descrizione di un sensore binario con funzione di estrazione."""

    value_fn: Callable[[dict], bool | None]


BINARY_SENSORS: tuple[HikBinaryDescription, ...] = (
    HikBinaryDescription(
        key="ac_power",
        translation_key="ac_power",
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.get("ac_connect"),
    ),
    HikBinaryDescription(
        key="tamper",
        translation_key="tamper",
        device_class=BinarySensorDeviceClass.TAMPER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.get("tamper"),
    ),
    HikBinaryDescription(
        key="cloud",
        translation_key="cloud",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: (h.get("cloud_status") == "normal") if h.get("cloud_status") else None,
    ),
    HikBinaryDescription(
        key="mobile",
        translation_key="mobile",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: (h.get("mobile_status") == "normal") if h.get("mobile_status") else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HikAxProCoordinator = hass.data[DOMAIN][entry.entry_id]
    if (coordinator.data or {}).get("host") is None:
        return
    async_add_entities(HikAxProBinary(coordinator, desc) for desc in BINARY_SENSORS)


class HikAxProBinary(HikAxProEntity, BinarySensorEntity):
    """Un sensore binario diagnostico."""

    entity_description: HikBinaryDescription

    def __init__(self, coordinator: HikAxProCoordinator, description: HikBinaryDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.client.serial}_{description.key}"

    @property
    def available(self) -> bool:
        return super().available and self._host is not None and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        host = self._host
        if host is None:
            return None
        return self.entity_description.value_fn(host)

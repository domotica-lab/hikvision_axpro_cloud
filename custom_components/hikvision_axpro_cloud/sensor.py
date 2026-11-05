"""Sensori diagnostici della centrale (batteria, segnale, SIM, consumo dati)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HikAxProCoordinator
from .entity import HikAxProEntity


@dataclass(frozen=True, kw_only=True)
class HikSensorDescription(SensorEntityDescription):
    """Descrizione di un sensore con funzione di estrazione valore."""

    value_fn: Callable[[dict], object]


SENSORS: tuple[HikSensorDescription, ...] = (
    HikSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.get("battery_percent"),
    ),
    HikSensorDescription(
        key="mobile_signal",
        translation_key="mobile_signal",
        icon="mdi:signal",
        native_unit_of_measurement="bars",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.get("mobile_signal"),
    ),
    HikSensorDescription(
        key="sim_operator",
        translation_key="sim_operator",
        icon="mdi:sim",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: (h.get("sim_operator") or "").strip() or None,
    ),
    HikSensorDescription(
        key="data_flow",
        translation_key="data_flow",
        icon="mdi:database",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.get("flow"),
    ),
    HikSensorDescription(
        key="faults",
        translation_key="faults",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda h: h.get("fault_num"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HikAxProCoordinator = hass.data[DOMAIN][entry.entry_id]
    if (coordinator.data or {}).get("host") is None:
        return  # la centrale non espone la diagnostica: niente sensori
    async_add_entities(HikAxProSensor(coordinator, desc) for desc in SENSORS)


class HikAxProSensor(HikAxProEntity, SensorEntity):
    """Un sensore diagnostico della centrale."""

    entity_description: HikSensorDescription

    def __init__(self, coordinator: HikAxProCoordinator, description: HikSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.client.serial}_{description.key}"

    @property
    def available(self) -> bool:
        return super().available and self._host is not None

    @property
    def native_value(self):
        host = self._host
        if host is None:
            return None
        return self.entity_description.value_fn(host)

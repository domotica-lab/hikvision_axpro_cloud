"""Entità alarm_control_panel per ogni area attiva della centrale."""
from __future__ import annotations

import logging
import time

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .api import HikAxProError
from .const import CONF_ARM_HOME, CONF_CODE, DOMAIN
from .coordinator import HikAxProCoordinator
from .entity import HikAxProEntity

_LOGGER = logging.getLogger(__name__)

STATE_TO_HA = {
    "disarmed": AlarmControlPanelState.DISARMED,
    "armed_away": AlarmControlPanelState.ARMED_AWAY,
    "armed_home": AlarmControlPanelState.ARMED_HOME,
    "arming": AlarmControlPanelState.ARMING,
    "disarming": AlarmControlPanelState.DISARMING,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Crea un pannello allarme per ogni area attiva."""
    coordinator: HikAxProCoordinator = hass.data[DOMAIN][entry.entry_id]
    areas = (coordinator.data or {}).get("areas") or {}
    single = len(areas) == 1
    async_add_entities(HikAxProAlarm(coordinator, area_id, single) for area_id in areas)


class HikAxProAlarm(HikAxProEntity, AlarmControlPanelEntity):
    """Un'area della centrale AX PRO come pannello allarme."""

    def __init__(self, coordinator: HikAxProCoordinator, area_id: int, single: bool = False) -> None:
        super().__init__(coordinator)
        self._area_id = area_id
        self._single = single
        self._attr_unique_id = f"{coordinator.client.serial}_area{area_id}"
        self._optimistic: AlarmControlPanelState | None = None
        self._refresh_timers: list = []
        self._opt_expire = 0.0
        opts = coordinator.entry.options
        code = (opts.get(CONF_CODE) or "").strip()
        self._code = code or None
        # Il codice protegge solo il disinserimento; l'inserimento resta con un tocco.
        self._attr_code_arm_required = False
        if self._code:
            self._attr_code_format = CodeFormat.NUMBER if code.isdigit() else CodeFormat.TEXT
        else:
            self._attr_code_format = None
        features = AlarmControlPanelEntityFeature.ARM_AWAY
        if opts.get(CONF_ARM_HOME):
            features |= AlarmControlPanelEntityFeature.ARM_HOME
        self._attr_supported_features = features

    @property
    def _area(self) -> dict | None:
        return ((self.coordinator.data or {}).get("areas") or {}).get(self._area_id)

    @property
    def available(self) -> bool:
        return super().available and self._area is not None

    @property
    def name(self) -> str | None:
        # Con una sola area l'allarme è l'entità principale del dispositivo:
        # mostra direttamente il nome del dispositivo (stile integrazioni ufficiali).
        if self._single:
            return None
        area = self._area
        return area["name"] if area else f"Area {self._area_id}"

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        area = self._area
        if not area:
            return None
        real = (
            AlarmControlPanelState.TRIGGERED
            if area.get("alarm")
            else STATE_TO_HA.get(area["state"])
        )
        # Stato ottimistico: mostra subito l'esito del comando (come l'app),
        # finché la centrale non conferma lo stato finale o scade il tempo.
        if self._optimistic is not None:
            if time.monotonic() > self._opt_expire or real == self._optimistic:
                self._optimistic = None
            else:
                return self._optimistic
        return real

    def _check_code(self, code: str | None) -> None:
        if self._code and code != self._code:
            raise ServiceValidationError("Wrong code")

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        self._check_code(code)
        await self._run(self.coordinator.client.disarm, AlarmControlPanelState.DISARMED)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._run(self.coordinator.client.arm_away, AlarmControlPanelState.ARMED_AWAY)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self._run(self.coordinator.client.arm_home, AlarmControlPanelState.ARMED_HOME)

    async def _run(self, func, target: AlarmControlPanelState) -> None:
        try:
            await func(self._area_id)
        except HikAxProError as err:
            _LOGGER.error("Alarm command failed: %s", err)
            raise HomeAssistantError(f"Alarm command failed: {err}") from err
        # mostra subito l'esito (come l'app) e poi conferma col polling
        self._optimistic = target
        self._opt_expire = time.monotonic() + 60
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
        # qualche rilettura ravvicinata per catturare in fretta lo stato reale
        self._cancel_refresh_timers()
        for delay in (3, 8, 20, 35):
            self._refresh_timers.append(
                async_call_later(self.hass, delay, self._delayed_refresh)
            )

    async def _delayed_refresh(self, _now) -> None:
        await self.coordinator.async_request_refresh()

    def _cancel_refresh_timers(self) -> None:
        for cancel in self._refresh_timers:
            cancel()
        self._refresh_timers.clear()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_refresh_timers()
        await super().async_will_remove_from_hass()

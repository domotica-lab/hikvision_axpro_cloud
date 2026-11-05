"""Procedura di configurazione (email + password Hik-Connect) + opzioni + reauth."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import HikAxProAuthError, HikAxProCloud, HikAxProError
from .const import (
    CONF_ACCOUNT,
    CONF_ARM_HOME,
    CONF_CODE,
    CONF_FEATURE_CODE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

SCHEMA = vol.Schema(
    {vol.Required(CONF_ACCOUNT): str, vol.Required(CONF_PASSWORD): str}
)


def _panel_label(panel: dict) -> str:
    name = panel.get("name") or "AX PRO"
    model = f" {panel['model']}" if panel.get("model") else ""
    return f"{name} ({panel['serial']}{model})"


class HikAxProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gestisce la configurazione guidata e la ri-autenticazione."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: HikAxProCloud | None = None
        self._user_input: dict[str, Any] = {}
        self._panels: list[dict] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._client = HikAxProCloud(
                account=user_input[CONF_ACCOUNT],
                password=user_input[CONF_PASSWORD],
                session=async_get_clientsession(self.hass),
            )
            try:
                panels = await self._client.list_panels()
            except HikAxProAuthError:
                errors["base"] = "invalid_auth"
            except HikAxProError as err:
                _LOGGER.warning("Setup failed: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"
            else:
                configured = self._async_current_ids()
                self._panels = [p for p in panels if p["serial"] not in configured]
                self._user_input = user_input
                if not panels:
                    errors["base"] = "no_panels"
                elif not self._panels:
                    return self.async_abort(reason="already_configured")
                elif len(self._panels) == 1:
                    return await self._async_create(self._panels[0]["serial"])
                else:
                    return await self.async_step_select_panel()
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_select_panel(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Più centrali sull'account: l'utente sceglie quale aggiungere."""
        if user_input is not None:
            return await self._async_create(user_input[CONF_SERIAL])
        options = [
            SelectOptionDict(value=p["serial"], label=_panel_label(p)) for p in self._panels
        ]
        return self.async_show_form(
            step_id="select_panel",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERIAL): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def _async_create(self, serial: str) -> ConfigFlowResult:
        """Verifica l'accesso alla centrale scelta e crea la voce."""
        assert self._client is not None
        client = HikAxProCloud(
            account=self._user_input[CONF_ACCOUNT],
            password=self._user_input[CONF_PASSWORD],
            session=async_get_clientsession(self.hass),
            serial=serial,
            feature_code=self._client.feature_code,
        )
        try:
            await client.ensure_ready()
        except HikAxProError as err:
            _LOGGER.warning("Panel %s not accessible: %s", serial, err)
            return self.async_abort(reason="panel_not_accessible")
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured()
        name = client.device_name or "AX PRO"
        return self.async_create_entry(
            title=f"{name} ({serial})",
            data={
                CONF_ACCOUNT: self._user_input[CONF_ACCOUNT],
                CONF_PASSWORD: self._user_input[CONF_PASSWORD],
                CONF_SERIAL: serial,
                CONF_FEATURE_CODE: client.feature_code,
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            client = HikAxProCloud(
                account=entry.data[CONF_ACCOUNT],
                password=user_input[CONF_PASSWORD],
                session=async_get_clientsession(self.hass),
                serial=entry.data.get(CONF_SERIAL),
                feature_code=entry.data.get(CONF_FEATURE_CODE),
            )
            try:
                await client.ensure_ready()
            except HikAxProAuthError:
                errors["base"] = "invalid_auth"
            except HikAxProError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during re-authentication")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HikAxProOptionsFlow()


class HikAxProOptionsFlow(OptionsFlow):
    """Opzioni: intervallo, PIN, inserimento parziale."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                    vol.Optional(CONF_CODE, default=opts.get(CONF_CODE, "")): str,
                    vol.Required(
                        CONF_ARM_HOME, default=opts.get(CONF_ARM_HOME, False)
                    ): bool,
                }
            ),
        )

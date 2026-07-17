"""Config + options flow for VerdiGrow.

Connection is configured here. The sensor→metric MAP is authored in VerdiGrow's
console (Sensor Mapping) — this integration pulls it and pushes readings — so the
only option here is how often to push.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import VerdiGrowClient, VerdiGrowError
from .const import (CONF_INTERVAL, CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL,
                    DEFAULT_INTERVAL, DOMAIN)

_LOGGER = logging.getLogger(__name__)


class VerdiGrowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        detail = ""
        data = user_input or {}
        if user_input is not None:
            client = VerdiGrowClient(self.hass, user_input[CONF_URL], user_input[CONF_TOKEN],
                                     user_input.get(CONF_VERIFY_SSL, True))
            try:
                await client.async_ping()
            except VerdiGrowError as e:
                detail = str(e)
                _LOGGER.warning("VerdiGrow connect failed: %s", detail)
                errors["base"] = "invalid_auth" if "unauthorized" in detail else "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="VerdiGrow", data=user_input)
        # Re-show with the values already entered so nothing has to be re-typed.
        schema = vol.Schema({
            vol.Required(CONF_URL, default=data.get(CONF_URL, "")): str,
            vol.Required(CONF_TOKEN, default=data.get(CONF_TOKEN, "")): str,
            vol.Required(CONF_VERIFY_SSL, default=data.get(CONF_VERIFY_SSL, True)): bool,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors,
                                    description_placeholders={"detail": detail})

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return VerdiGrowOptionsFlow(entry)


class VerdiGrowOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry) -> None:
        self.entry = entry
        self._options = dict(entry.options)

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            self._options[CONF_INTERVAL] = user_input[CONF_INTERVAL]
            return self.async_create_entry(title="", data=self._options)
        schema = vol.Schema({
            vol.Required(CONF_INTERVAL,
                         default=self._options.get(CONF_INTERVAL, DEFAULT_INTERVAL)):
                selector.NumberSelector(selector.NumberSelectorConfig(
                    min=60, max=86400, step=60, unit_of_measurement="seconds", mode="box")),
        })
        return self.async_show_form(step_id="init", data_schema=schema)

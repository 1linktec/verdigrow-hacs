"""Config + options flow for VerdiGrow.

Connection is configured here. The sensor→metric MAP is authored in VerdiGrow's
console (Sensor Mapping) — this integration pulls it and pushes readings — so the
only option here is how often to push.
"""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .api import VerdiGrowClient, VerdiGrowError
from .const import (
    CONF_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# A token is a secret, so the field hides it and offers an eye to reveal — the same
# treatment as a password. Typing one blind is how a typo becomes "cannot connect".
TOKEN_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


async def _check(hass, url, token, verify_ssl):
    """Try the connection. Returns (error_key, detail) — (None, "") if it worked."""
    client = VerdiGrowClient(hass, url, token, verify_ssl)
    try:
        await client.async_ping()
    except VerdiGrowError as e:
        detail = str(e)
        _LOGGER.warning("VerdiGrow connect failed: %s", detail)
        return (
            "invalid_auth" if "unauthorized" in detail else "cannot_connect"
        ), detail
    return None, ""


class VerdiGrowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        detail = ""
        data = user_input or {}
        if user_input is not None:
            err, detail = await _check(
                self.hass,
                user_input[CONF_URL],
                user_input[CONF_TOKEN],
                user_input.get(CONF_VERIFY_SSL, True),
            )
            if err:
                errors["base"] = err
            else:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="VerdiGrow", data=user_input)
        # Re-show with the values already entered so nothing has to be re-typed.
        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=data.get(CONF_URL, "")): str,
                vol.Required(
                    CONF_TOKEN, default=data.get(CONF_TOKEN, "")
                ): TOKEN_SELECTOR,
                vol.Required(
                    CONF_VERIFY_SSL, default=data.get(CONF_VERIFY_SSL, True)
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"detail": detail},
        )

    async def async_step_reauth(self, entry_data):
        """The stored token stopped being accepted."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Ask for a new token, keeping the URL that already works.

        Without this, rotating the API token in VerdiGrow leaves every entity
        unavailable and nothing on screen saying why — the grower has to guess that
        the fix lives in the options flow. HA raises this automatically once the
        coordinator reports ConfigEntryAuthFailed.
        """
        entry = self._get_reauth_entry()
        errors = {}
        detail = ""
        if user_input is not None:
            err, detail = await _check(
                self.hass,
                entry.data[CONF_URL],
                user_input[CONF_TOKEN],
                entry.data.get(CONF_VERIFY_SSL, True),
            )
            if err:
                errors["base"] = err
            else:
                # Updates the entry and reloads it in one step, which is what makes
                # the entities come back without the grower restarting anything.
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: user_input[CONF_TOKEN]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): TOKEN_SELECTOR}),
            errors=errors,
            description_placeholders={
                "url": entry.data[CONF_URL],
                "detail": detail,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return VerdiGrowOptionsFlow()


class VerdiGrowOptionsFlow(config_entries.OptionsFlow):
    """Edit the connection and the push interval.

    Takes no entry: `self.config_entry` is provided by the base class. Storing our
    own copy was the older pattern and HA now warns about it — a held reference can
    also go stale if the entry is updated while the dialog is open.
    """

    async def async_step_init(self, user_input=None):
        errors = {}
        detail = ""
        self._options = dict(self.config_entry.options)
        data = {**self.config_entry.data}
        if user_input is not None:
            # Validate the (possibly changed) endpoint before saving.
            err, detail = await _check(
                self.hass,
                user_input[CONF_URL],
                user_input[CONF_TOKEN],
                user_input.get(CONF_VERIFY_SSL, True),
            )
            if err:
                errors["base"] = err
            else:
                # Persist the connection (URL/token/verify-SSL) to entry.data; the
                # entry update listener (_reload_on_options) reloads to apply it.
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        CONF_URL: user_input[CONF_URL],
                        CONF_TOKEN: user_input[CONF_TOKEN],
                        CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, True),
                    },
                )
                self._options[CONF_INTERVAL] = user_input[CONF_INTERVAL]
                return self.async_create_entry(title="", data=self._options)
        # Endpoint fields default to the current values so you edit in place — no
        # need to delete + re-add the integration to change the URL or token.
        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=data.get(CONF_URL, "")): str,
                vol.Required(
                    CONF_TOKEN, default=data.get(CONF_TOKEN, "")
                ): TOKEN_SELECTOR,
                vol.Required(
                    CONF_VERIFY_SSL, default=data.get(CONF_VERIFY_SSL, True)
                ): bool,
                vol.Required(
                    CONF_INTERVAL,
                    default=self._options.get(CONF_INTERVAL, DEFAULT_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=60,
                        max=86400,
                        step=60,
                        unit_of_measurement="seconds",
                        mode="box",
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={"detail": detail},
        )

"""Config + options flow for VerdiGrow."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import VerdiGrowClient, VerdiGrowError
from .const import (CONF_INTERVAL, CONF_MAPPINGS, CONF_TOKEN, CONF_URL,
                    DEFAULT_INTERVAL, DOMAIN, TARGET_AREA, TARGET_CONTAINER)


class VerdiGrowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            client = VerdiGrowClient(self.hass, user_input[CONF_URL], user_input[CONF_TOKEN])
            try:
                await client.async_ping()
            except VerdiGrowError as e:
                errors["base"] = "invalid_auth" if "unauthorized" in str(e) else "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="VerdiGrow", data=user_input)
        schema = vol.Schema({
            vol.Required(CONF_URL, default="http://verdigrow.local:8095"): str,
            vol.Required(CONF_TOKEN): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return VerdiGrowOptionsFlow(entry)


class VerdiGrowOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry) -> None:
        self.entry = entry
        self._options = dict(entry.options)
        self._options.setdefault(CONF_MAPPINGS, [])

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["interval", "add_mapping", "remove_mapping"],
        )

    async def async_step_interval(self, user_input=None):
        if user_input is not None:
            self._options[CONF_INTERVAL] = user_input[CONF_INTERVAL]
            return self.async_create_entry(title="", data=self._options)
        schema = vol.Schema({
            vol.Required(CONF_INTERVAL,
                         default=self._options.get(CONF_INTERVAL, DEFAULT_INTERVAL)):
                selector.NumberSelector(selector.NumberSelectorConfig(
                    min=60, max=86400, step=60, unit_of_measurement="seconds",
                    mode="box")),
        })
        return self.async_show_form(step_id="interval", data_schema=schema)

    async def async_step_add_mapping(self, user_input=None):
        client = VerdiGrowClient(self.hass, self.entry.data[CONF_URL], self.entry.data[CONF_TOKEN])
        try:
            containers = await client.async_containers()
            areas = await client.async_areas()
            metrics = await client.async_metric_types()
        except VerdiGrowError:
            return self.async_abort(reason="cannot_connect")

        targets = [{"value": f"{TARGET_CONTAINER}:{c['id']}", "label": f"Container: {c['label']}"}
                   for c in containers]
        targets += [{"value": f"{TARGET_AREA}:{a['id']}", "label": f"Area: {a['name']}"}
                    for a in areas]
        metric_opts = [{"value": m["key"], "label": f"{m['name']} ({m['unit']})"} for m in metrics]

        if user_input is not None:
            # One sensor can map to several VerdiGrow targets (e.g. an HA area
            # sensor feeding both the Garden Wall and the Raised Beds).
            for target in user_input["targets"]:
                tkind, tid = target.split(":", 1)
                self._options[CONF_MAPPINGS].append({
                    "entity_id": user_input["entity_id"],
                    "target": tkind, "id": int(tid), "metric": user_input["metric"],
                })
            return self.async_create_entry(title="", data=self._options)

        schema = vol.Schema({
            vol.Required("entity_id"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "binary_sensor", "number"])),
            vol.Required("targets"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=targets, multiple=True, mode="dropdown")),
            vol.Required("metric"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=metric_opts, mode="dropdown")),
        })
        return self.async_show_form(step_id="add_mapping", data_schema=schema)

    async def async_step_remove_mapping(self, user_input=None):
        maps = self._options.get(CONF_MAPPINGS, [])
        if not maps:
            return self.async_abort(reason="no_mappings")
        options = [{"value": str(i),
                    "label": f"{m['entity_id']} → {m['target']} {m['id']} ({m['metric']})"}
                   for i, m in enumerate(maps)]
        if user_input is not None:
            keep = set(user_input.get("remove", []))
            self._options[CONF_MAPPINGS] = [m for i, m in enumerate(maps) if str(i) not in keep]
            return self.async_create_entry(title="", data=self._options)
        schema = vol.Schema({
            vol.Optional("remove", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, multiple=True, mode="list")),
        })
        return self.async_show_form(step_id="remove_mapping", data_schema=schema)

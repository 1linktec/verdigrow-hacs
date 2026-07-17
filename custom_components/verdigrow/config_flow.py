"""Config + options flow for VerdiGrow."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import (area_registry as ar, device_registry as dr,
                                   entity_registry as er, selector)

from .api import VerdiGrowClient, VerdiGrowError
from .const import (CONF_AREA_LINKS, CONF_INTERVAL, CONF_MAPPINGS, CONF_TOKEN,
                    CONF_URL, DEFAULT_INTERVAL, DOMAIN, TARGET_AREA,
                    TARGET_CONTAINER)

_SENSOR_DOMAINS = ("sensor.", "binary_sensor.", "number.")


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
            vol.Required(CONF_URL): selector.TextSelector(
                selector.TextSelectorConfig(type="url")),
            vol.Required(CONF_TOKEN): selector.TextSelector(
                selector.TextSelectorConfig(type="password")),
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
        self._options.setdefault(CONF_AREA_LINKS, [])

    def _client(self):
        return VerdiGrowClient(self.hass, self.entry.data[CONF_URL], self.entry.data[CONF_TOKEN])

    async def _vg_target_options(self):
        """All VerdiGrow containers+areas as [{value,label}] (from the read API)."""
        client = self._client()
        containers = await client.async_containers()
        areas = await client.async_areas()
        opts = [{"value": f"{TARGET_CONTAINER}:{c['id']}", "label": f"Container: {c['label']}"}
                for c in containers]
        opts += [{"value": f"{TARGET_AREA}:{a['id']}", "label": f"Area: {a['name']}"} for a in areas]
        return opts

    def _entities_in_areas(self, area_ids):
        """Sensor-ish entities whose (own or device) area is in area_ids."""
        ereg, dreg = er.async_get(self.hass), dr.async_get(self.hass)
        out = []
        for ent in ereg.entities.values():
            if not ent.entity_id.startswith(_SENSOR_DOMAINS):
                continue
            aid = ent.area_id
            if aid is None and ent.device_id:
                dev = dreg.async_get(ent.device_id)
                aid = dev.area_id if dev else None
            if aid in area_ids:
                out.append({"value": ent.entity_id,
                            "label": ent.name or ent.original_name or ent.entity_id})
        out.sort(key=lambda e: e["label"].lower())
        return out

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["map_area", "add_mapping", "remove_mapping", "interval"],
        )

    async def async_step_interval(self, user_input=None):
        if user_input is not None:
            self._options[CONF_INTERVAL] = user_input[CONF_INTERVAL]
            return self.async_create_entry(title="", data=self._options)
        schema = vol.Schema({
            vol.Required(CONF_INTERVAL,
                         default=self._options.get(CONF_INTERVAL, DEFAULT_INTERVAL)):
                selector.NumberSelector(selector.NumberSelectorConfig(
                    min=60, max=86400, step=60, unit_of_measurement="seconds", mode="box")),
        })
        return self.async_show_form(step_id="interval", data_schema=schema)

    async def async_step_map_area(self, user_input=None):
        """Link an HA area to one or more VerdiGrow targets. This scopes the
        sensor picker (only entities in linked HA areas are offered)."""
        try:
            targets = await self._vg_target_options()
        except VerdiGrowError:
            return self.async_abort(reason="cannot_connect")
        if user_input is not None:
            areg = ar.async_get(self.hass)
            ha_area = areg.async_get_area(user_input["ha_area"])
            chosen = [t for t in targets if t["value"] in user_input["targets"]]
            self._options[CONF_AREA_LINKS].append({
                "ha_area_id": user_input["ha_area"],
                "ha_area_name": ha_area.name if ha_area else user_input["ha_area"],
                "targets": chosen,
            })
            return self.async_create_entry(title="", data=self._options)
        schema = vol.Schema({
            vol.Required("ha_area"): selector.AreaSelector(),
            vol.Required("targets"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=targets, multiple=True, mode="dropdown")),
        })
        return self.async_show_form(step_id="map_area", data_schema=schema)

    async def async_step_add_mapping(self, user_input=None):
        links = self._options.get(CONF_AREA_LINKS, [])
        if not links:
            return self.async_abort(reason="map_area_first")
        area_ids = [l["ha_area_id"] for l in links]
        entities = self._entities_in_areas(area_ids)
        if not entities:
            return self.async_abort(reason="no_entities_in_areas")
        # Targets offered = the VG targets linked to those HA areas (tight list).
        seen, target_opts = set(), []
        for l in links:
            for t in l["targets"]:
                if t["value"] not in seen:
                    seen.add(t["value"]); target_opts.append(t)
        try:
            metrics = await self._client().async_metric_types()
        except VerdiGrowError:
            return self.async_abort(reason="cannot_connect")
        metric_opts = [{"value": m["key"], "label": f"{m['name']} ({m['unit']})"} for m in metrics]

        if user_input is not None:
            for target in user_input["targets"]:
                tkind, tid = target.split(":", 1)
                self._options[CONF_MAPPINGS].append({
                    "entity_id": user_input["entity_id"],
                    "target": tkind, "id": int(tid), "metric": user_input["metric"],
                })
            return self.async_create_entry(title="", data=self._options)

        schema = vol.Schema({
            vol.Required("entity_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=entities, mode="dropdown")),
            vol.Required("targets", default=[t["value"] for t in target_opts]):
                selector.SelectSelector(selector.SelectSelectorConfig(
                    options=target_opts, multiple=True, mode="dropdown")),
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
            drop = set(user_input.get("remove", []))
            self._options[CONF_MAPPINGS] = [m for i, m in enumerate(maps) if str(i) not in drop]
            return self.async_create_entry(title="", data=self._options)
        schema = vol.Schema({
            vol.Optional("remove", default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, multiple=True, mode="list")),
        })
        return self.async_show_form(step_id="remove_mapping", data_schema=schema)

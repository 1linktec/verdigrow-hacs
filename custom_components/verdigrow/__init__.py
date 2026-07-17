"""
VerdiGrow — Home Assistant integration.

HA is the sensor hub and the home of all HA management. This integration ships a
custom sidebar **panel** (the tree/filter sensor-mapping UI), stores that map in
HA, and PUSHES readings to VerdiGrow's ingest API on a configurable interval
(default 1 hour). VerdiGrow only stores readings and serves a read-only catalog —
it is not an extension of HA. No hardware access; no dashboards rendered here.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import VerdiGrowClient, VerdiGrowError
from .const import (CONF_INTERVAL, CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL,
                    DEFAULT_INTERVAL, DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL,
                    STATIC_URL, STORAGE_KEY, STORAGE_VERSION,
                    TARGET_AREA, TARGET_CONTAINER)
from .http_api import (VerdiGrowAreasView, VerdiGrowCardsView,
                       VerdiGrowCatalogView, VerdiGrowMappingsView,
                       VerdiGrowPushView)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = []
_UNAVAILABLE = ("unknown", "unavailable", "", None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = VerdiGrowClient(hass, entry.data[CONF_URL], entry.data[CONF_TOKEN],
                             entry.data.get(CONF_VERIFY_SSL, True))
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    hass.data.setdefault(DOMAIN, {})

    async def _push(_now=None) -> int:
        data = await store.async_load() or {}
        links = data.get("links", [])
        if not links:
            return 0

        def _value(entity_id):
            st = hass.states.get(entity_id or "")
            if st is None or st.state in _UNAVAILABLE:
                return None
            try:
                return float(st.state)
            except (TypeError, ValueError):
                return None

        # Which (container, metric) pairs have a DEDICATED sensor. Ambient
        # (area) sensors are skipped for those pairs — a container's own sensor
        # for a metric wins over the area's ambient sensor for that same metric.
        dedicated = {(l["id"], l["metric"]) for l in links
                     if l.get("target") == TARGET_CONTAINER}

        # Area -> its current container ids, for ambient fan-out (done here in HA
        # so the dedicated-overrides-ambient rule can be applied per metric).
        area_containers = {}
        if any(l.get("target") == TARGET_AREA for l in links):
            try:
                for c in await client.async_containers():
                    if c.get("area_id"):
                        area_containers.setdefault(c["area_id"], []).append(c["id"])
            except VerdiGrowError as e:
                _LOGGER.warning("VerdiGrow: could not fetch containers for ambient fan-out: %s", e)

        now = dt_util.utcnow().isoformat()
        readings = []
        for m in links:
            value = _value(m.get("entity_id"))
            if value is None:
                continue
            base = {"metric": m["metric"], "value": value,
                    "occurred_at": now, "entity_id": m["entity_id"]}
            target = m.get("target")
            if target == TARGET_CONTAINER:
                readings.append({**base, "container_id": m["id"]})
            elif target == TARGET_AREA:
                # Fan out to every container in the area, except ones with their
                # own dedicated sensor for this metric (auto) or ones the user
                # manually excluded from this ambient sensor.
                exclude = set(m.get("exclude") or [])
                for cid in area_containers.get(m["id"], []):
                    if (cid, m["metric"]) in dedicated or cid in exclude:
                        continue
                    readings.append({**base, "container_id": cid})
            # plants are not mapping targets
        if not readings:
            return 0
        try:
            result = await client.async_push(readings)
            _LOGGER.debug("VerdiGrow pushed %s reading(s): %s", len(readings), result)
            return len(readings)
        except VerdiGrowError as e:
            _LOGGER.warning("VerdiGrow push failed: %s", e)
            return 0

    hass.data[DOMAIN]["runtime"] = {"client": client, "store": store, "push": _push}

    # Register the local HTTP endpoints the panel calls (once).
    if not hass.data[DOMAIN].get("_views"):
        hass.http.register_view(VerdiGrowCatalogView(hass))
        hass.http.register_view(VerdiGrowMappingsView(hass))
        hass.http.register_view(VerdiGrowAreasView(hass))
        hass.http.register_view(VerdiGrowCardsView(hass))
        hass.http.register_view(VerdiGrowPushView(hass))
        hass.data[DOMAIN]["_views"] = True

    # Register the custom sidebar panel (once).
    if not hass.data[DOMAIN].get("_panel"):
        frontend_dir = str(Path(__file__).parent / "frontend")
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, frontend_dir, False)])
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="verdigrow-panel",
            module_url=f"{STATIC_URL}/verdigrow-panel.js",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            require_admin=False,
            embed_iframe=False,
        )
        hass.data[DOMAIN]["_panel"] = True

    interval = int(entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL))
    unsub = async_track_time_interval(hass, _push, timedelta(seconds=interval))
    hass.data[DOMAIN][entry.entry_id] = {"unsub": unsub}

    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    hass.async_create_task(_push())
    return True


async def _reload_on_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data and data.get("unsub"):
        data["unsub"]()
    # If this was the last entry, tear down the shared panel + runtime.
    remaining = [k for k in hass.data.get(DOMAIN, {})
                 if k not in ("_views", "_panel", "runtime")]
    if not remaining:
        hass.data.get(DOMAIN, {}).pop("runtime", None)
        if hass.data.get(DOMAIN, {}).pop("_panel", False):
            from homeassistant.components import frontend
            frontend.async_remove_panel(hass, PANEL_URL)
    return True

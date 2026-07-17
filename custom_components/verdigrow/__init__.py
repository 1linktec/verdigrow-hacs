"""
VerdiGrow — Home Assistant integration.

Push model: HA is the sensor hub. This integration reads the mapped HA entity
states and PUSHES readings to VerdiGrow's ingest API on a configurable interval
(default 1 hour). VerdiGrow only stores metrics — it never pulls from HA.
No hardware access; no dashboards rendered here.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .api import VerdiGrowClient, VerdiGrowError
from .const import (CONF_INTERVAL, CONF_MAPPINGS, CONF_TOKEN, CONF_URL,
                    DEFAULT_INTERVAL, DOMAIN, TARGET_AREA, TARGET_CONTAINER)

_LOGGER = logging.getLogger(__name__)

# No HA entities created by this integration (push-only). Dashboards/cards are a
# later phase.
PLATFORMS: list[str] = []

_UNAVAILABLE = ("unknown", "unavailable", "", None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = VerdiGrowClient(hass, entry.data[CONF_URL], entry.data[CONF_TOKEN])
    hass.data.setdefault(DOMAIN, {})

    async def _push(_now=None):
        mappings = entry.options.get(CONF_MAPPINGS, [])
        if not mappings:
            return
        readings = []
        for m in mappings:
            state = hass.states.get(m["entity_id"])
            if state is None or state.state in _UNAVAILABLE:
                continue
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                continue
            r = {"metric": m["metric"], "value": value,
                 "occurred_at": dt_util.utcnow().isoformat(),
                 "entity_id": m["entity_id"]}
            if m["target"] == TARGET_CONTAINER:
                r["container_id"] = m["id"]
            elif m["target"] == TARGET_AREA:
                r["area_id"] = m["id"]
            readings.append(r)
        if not readings:
            return
        try:
            result = await client.async_push(readings)
            _LOGGER.debug("VerdiGrow push: %s", result)
        except VerdiGrowError as e:
            _LOGGER.warning("VerdiGrow push failed: %s", e)

    interval = int(entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL))
    unsub = async_track_time_interval(hass, _push, timedelta(seconds=interval))
    hass.data[DOMAIN][entry.entry_id] = {"client": client, "unsub": unsub, "push": _push}

    # Push once shortly after setup so data appears without waiting a full interval.
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    hass.async_create_task(_push())

    if PLATFORMS:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload_on_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-apply interval/mappings when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data and data.get("unsub"):
        data["unsub"]()
    if PLATFORMS:
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return True

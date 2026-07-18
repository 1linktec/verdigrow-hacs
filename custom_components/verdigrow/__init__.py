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
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr_helper
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import VerdiGrowClient, VerdiGrowError
from .const import (CONF_INTERVAL, CONF_TOKEN, CONF_URL, CONF_VERIFY_SSL,
                    DEFAULT_INTERVAL, DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL,
                    STATIC_URL, STORAGE_KEY, STORAGE_VERSION,
                    TARGET_AREA, TARGET_CONTAINER)
from .coordinator import VerdiGrowCoordinator
from .http_api import (VerdiGrowAreasView, VerdiGrowCardsView,
                       VerdiGrowCatalogView, VerdiGrowMappingsView,
                       VerdiGrowPushView)

_LOGGER = logging.getLogger(__name__)

# Containers become HA devices with sensor + image entities on their area.
PLATFORMS: list[str] = ["sensor", "image"]
_UNAVAILABLE = ("unknown", "unavailable", "", None)


def _lovelace_resources(hass: HomeAssistant):
    """The Lovelace resource collection, tolerant of HA storing the lovelace data
    as a dataclass (current) or a dict (older). Returns the collection only if it
    supports programmatic add (storage mode); None otherwise (YAML mode)."""
    data = hass.data.get("lovelace")
    resources = data.get("resources") if isinstance(data, dict) else getattr(data, "resources", None)
    # ResourceStorageCollection can add/update/delete; ResourceYAMLCollection can't.
    if resources is not None and hasattr(resources, "async_create_item"):
        return resources
    return None


async def _async_register_card_resource(hass: HomeAssistant, base_url: str,
                                        version: str | None) -> None:
    """Register the VerdiGrow card as a Lovelace *resource* — the documented way
    to ship a custom card from an integration (storage mode). The resource list
    is part of the Lovelace config every frontend fetches, including the Companion
    app, so the card loads like any HACS card. Version-stamps the URL and updates
    the existing resource on upgrade (cache-bust). Falls back to add_extra_js_url
    only if there's no storage resource collection (YAML mode)."""
    stamped = f"{base_url}?v={version}" if version else base_url

    def _fallback() -> None:
        from homeassistant.components.frontend import add_extra_js_url
        add_extra_js_url(hass, stamped)
        _LOGGER.warning("VerdiGrow: Lovelace not in storage mode — loaded the card "
                        "via extra_js_url (may not appear in the Companion app). "
                        "Add %s as a dashboard resource manually if needed.", stamped)

    async def _register(_event=None) -> None:
        resources = _lovelace_resources(hass)
        if resources is None:
            _fallback()  # YAML mode / lovelace absent — best effort
            return
        try:
            if not getattr(resources, "loaded", True):
                await resources.async_load()
            existing = next(
                (r for r in resources.async_items()
                 if str(r.get("url", "")).split("?")[0] == base_url), None)
            if existing is None:
                await resources.async_create_item(
                    {"res_type": "module", "url": stamped})
                _LOGGER.info("Registered VerdiGrow card Lovelace resource %s", stamped)
            elif existing.get("url") != stamped:
                await resources.async_update_item(
                    existing["id"], {"res_type": "module", "url": stamped})
                _LOGGER.info("Updated VerdiGrow card Lovelace resource to %s", stamped)
            else:
                _LOGGER.debug("VerdiGrow card Lovelace resource already current")
        except Exception:  # noqa: BLE001 — never block setup on the card
            _LOGGER.exception("Could not register VerdiGrow card resource; "
                              "falling back to extra_js_url")
            _fallback()

    # Lovelace resources aren't ready until HA has started.
    if hass.state == CoreState.running:
        await _register()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register)


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

    # Coordinator — polls containers so they show as HA devices/entities on
    # their area. Renames flow through (device name from the card); deletes drop
    # out of the data (their device is removed below); uninstall removes all
    # entities (they're registered under this config entry).
    interval = int(entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL))
    coordinator = VerdiGrowCoordinator(hass, client, interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN]["runtime"] = {"client": client, "store": store, "push": _push,
                                    "coordinator": coordinator}

    @callback
    def _manage_devices():
        """Remove devices for containers deleted in VerdiGrow; keep names in sync."""
        data = coordinator.data or {}
        reg = dr_helper.async_get(hass)
        for device in dr_helper.async_entries_for_config_entry(reg, entry.entry_id):
            cid = None
            for domain, ident in device.identifiers:
                if domain == DOMAIN and ident.startswith("container_"):
                    try:
                        cid = int(ident.split("_", 1)[1])
                    except ValueError:
                        cid = None
                    break
            if cid is None:
                continue
            card = data.get(cid)
            if card is None:
                reg.async_remove_device(device.id)  # gone in VerdiGrow → remove
            elif card.get("label") and device.name != card["label"] and not device.name_by_user:
                reg.async_update_device(device.id, name=card["label"])  # renamed

    entry.async_on_unload(coordinator.async_add_listener(_manage_devices))

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
        # Version-stamp the static URLs so a new release busts the browser AND the
        # Companion-app WebView cache (which otherwise serves a stale card/panel).
        try:
            manifest = await hass.async_add_executor_job(
                lambda: __import__("json").loads(
                    (Path(__file__).parent / "manifest.json").read_text()))
            ver = manifest.get("version")
        except Exception:  # noqa: BLE001 — cache-bust is best-effort
            ver = None
        stamp = f"?v={ver}" if ver else ""
        # Make `custom:verdigrow-container-card` available to dashboards. The
        # DOCUMENTED way to ship a card from an integration is to register it as a
        # Lovelace *resource* (res_type module) — the resource list is part of the
        # Lovelace config the frontend (incl. the Companion app) fetches, so the
        # card loads the same way HACS-installed cards do. add_extra_js_url only
        # injects it into the browser's main frontend and the app's Lovelace engine
        # doesn't reliably pick it up ("custom element doesn't exist").
        await _async_register_card_resource(
            hass, f"{STATIC_URL}/verdigrow-card.js", ver)
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="verdigrow-panel",
            module_url=f"{STATIC_URL}/verdigrow-panel.js{stamp}",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            require_admin=False,
            embed_iframe=False,
        )
        hass.data[DOMAIN]["_panel"] = True

    unsub = async_track_time_interval(hass, _push, timedelta(seconds=interval))
    hass.data[DOMAIN][entry.entry_id] = {"unsub": unsub, "coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _manage_devices()  # prune any devices for containers already gone

    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    hass.async_create_task(_push())
    return True


async def _reload_on_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
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
            await _async_remove_card_resource(hass)
    return unloaded


async def _async_remove_card_resource(hass: HomeAssistant) -> None:
    """Drop the Lovelace card resource on full uninstall (storage mode)."""
    resources = _lovelace_resources(hass)
    if resources is None:
        return
    try:
        if not getattr(resources, "loaded", True):
            await resources.async_load()
        for r in list(resources.async_items()):
            if str(r.get("url", "")).split("?")[0] == f"{STATIC_URL}/verdigrow-card.js":
                await resources.async_delete_item(r["id"])
    except Exception:  # noqa: BLE001 — best effort on teardown
        _LOGGER.exception("Could not remove VerdiGrow card resource")

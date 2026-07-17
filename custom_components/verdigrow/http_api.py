"""
Local HA HTTP endpoints backing the VerdiGrow sidebar panel.

The panel (frontend/verdigrow-panel.js) calls these same-origin, authenticated
by the logged-in HA user. They read VerdiGrow's read-only catalog (proxied with
the stored token) and read/write the sensor MAP — which lives here in HA, not in
VerdiGrow.
"""

from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers import area_registry as ar

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Short server-side cache so opening/reloading the panel is fast even after a
# full page reload (bypass/refresh with ?fresh=1).
_CACHE: dict = {}
_TTL = 120.0


def _cache_get(key):
    hit = _CACHE.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def _cache_put(key, data):
    _CACHE[key] = (time.monotonic() + _TTL, data)


def _cache_clear(*keys):
    for k in keys:
        _CACHE.pop(k, None)


def _runtime(hass):
    return hass.data.get(DOMAIN, {}).get("runtime")


class VerdiGrowCatalogView(HomeAssistantView):
    """GET /api/verdigrow/catalog — VerdiGrow objects the tree is built from."""

    url = "/api/verdigrow/catalog"
    name = "api:verdigrow:catalog"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        rt = _runtime(self.hass)
        if not rt:
            return self.json({"error": "VerdiGrow not set up"}, status_code=503)
        if not request.query.get("fresh"):
            cached = _cache_get("catalog")
            if cached is not None:
                return self.json(cached)
        client = rt["client"]
        try:
            containers, areas, plants, metric_types = await asyncio.gather(
                client.async_containers(), client.async_areas(),
                client.async_plants(), client.async_metric_types())
            data = {"containers": containers, "areas": areas,
                    "plants": plants, "metric_types": metric_types}
            _cache_put("catalog", data)
            return self.json(data)
        except Exception as e:  # noqa: BLE001 — surface to the panel
            _LOGGER.warning("catalog fetch failed: %s", e)
            return self.json({"error": str(e)}, status_code=502)


class VerdiGrowMappingsView(HomeAssistantView):
    """GET/POST /api/verdigrow/mappings — the sensor map (stored in HA)."""

    url = "/api/verdigrow/mappings"
    name = "api:verdigrow:mappings"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        rt = _runtime(self.hass)
        if not rt:
            return self.json({"links": []})
        data = await rt["store"].async_load() or {"links": []}
        return self.json(data)

    async def post(self, request):
        rt = _runtime(self.hass)
        if not rt:
            return self.json({"error": "VerdiGrow not set up"}, status_code=503)
        body = await request.json()
        links = body.get("links", [])
        if not isinstance(links, list):
            return self.json({"error": "'links' must be a list"}, status_code=400)
        data = await rt["store"].async_load() or {}
        data["links"] = links  # preserve other keys (e.g. area_map)
        await rt["store"].async_save(data)
        await rt["push"]()  # push straight away so it appears without waiting
        return self.json({"ok": True, "count": len(links)})


class VerdiGrowAreasView(HomeAssistantView):
    """Area sync. GET → HA areas + VerdiGrow areas + the stored VG→HA map.
    POST {action:'import', names:[…]} → create missing VG areas (matched by name).
    POST {action:'map', area_map:{vg_id: ha_area_id}} → save the mapping."""

    url = "/api/verdigrow/areas"
    name = "api:verdigrow:areas"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        rt = _runtime(self.hass)
        if not rt:
            return self.json({"error": "VerdiGrow not set up"}, status_code=503)
        areg = ar.async_get(self.hass)
        ha = sorted(({"area_id": a.id, "name": a.name} for a in areg.async_list_areas()),
                    key=lambda x: (x["name"] or "").lower())
        vg = _cache_get("vg_areas") if not request.query.get("fresh") else None
        if vg is None:
            try:
                vg = await rt["client"].async_areas()
            except Exception as e:  # noqa: BLE001
                return self.json({"error": str(e)}, status_code=502)
            _cache_put("vg_areas", vg)
        data = await rt["store"].async_load() or {}
        return self.json({"ha_areas": ha, "vg_areas": vg,
                          "area_map": data.get("area_map", {})})

    async def post(self, request):
        rt = _runtime(self.hass)
        if not rt:
            return self.json({"error": "VerdiGrow not set up"}, status_code=503)
        body = await request.json()
        action = body.get("action")
        if action == "import":
            try:
                result = await rt["client"].async_import_areas(body.get("names", []))
                _cache_clear("vg_areas", "catalog")  # areas changed
                return self.json(result)
            except Exception as e:  # noqa: BLE001
                return self.json({"error": str(e)}, status_code=502)
        if action == "create_ha_areas":
            # Create HA areas for VerdiGrow-owned areas the grower chose to add.
            areg = ar.async_get(self.hass)
            created = {}
            for name in body.get("names", []):
                name = (name or "").strip()
                if not name:
                    continue
                entry = areg.async_get_area_by_name(name) or areg.async_create(name)
                created[name] = entry.id
            return self.json({"created": created})
        if action == "map":
            data = await rt["store"].async_load() or {}
            data["area_map"] = body.get("area_map", {})
            await rt["store"].async_save(data)
            return self.json({"ok": True})
        return self.json({"error": "unknown action"}, status_code=400)


class VerdiGrowCardsView(HomeAssistantView):
    """Container cards. GET → the card list; GET ?id=<pk> → one card's detail
    (metrics + plants with latest photo & note)."""

    url = "/api/verdigrow/cards"
    name = "api:verdigrow:cards"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        rt = _runtime(self.hass)
        if not rt:
            return self.json({"error": "VerdiGrow not set up"}, status_code=503)
        try:
            if request.query.get("plant"):
                return self.json(await rt["client"].async_plant_card(request.query["plant"]))
            if request.query.get("id"):
                return self.json(await rt["client"].async_card(request.query["id"]))
            return self.json({"cards": await rt["client"].async_cards()})
        except Exception as e:  # noqa: BLE001
            return self.json({"error": str(e)}, status_code=502)


class VerdiGrowPushView(HomeAssistantView):
    """POST /api/verdigrow/push — push the current map now (for testing)."""

    url = "/api/verdigrow/push"
    name = "api:verdigrow:push"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def post(self, request):
        rt = _runtime(self.hass)
        if not rt:
            return self.json({"error": "VerdiGrow not set up"}, status_code=503)
        result = await rt["push"]()
        return self.json({"ok": True, "pushed": result or 0})

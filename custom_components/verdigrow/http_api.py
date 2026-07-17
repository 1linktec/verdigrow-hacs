"""
Local HA HTTP endpoints backing the VerdiGrow sidebar panel.

The panel (frontend/verdigrow-panel.js) calls these same-origin, authenticated
by the logged-in HA user. They read VerdiGrow's read-only catalog (proxied with
the stored token) and read/write the sensor MAP — which lives here in HA, not in
VerdiGrow.
"""

from __future__ import annotations

import logging

from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
        client = rt["client"]
        try:
            return self.json({
                "containers": await client.async_containers(),
                "areas": await client.async_areas(),
                "plants": await client.async_plants(),
                "metric_types": await client.async_metric_types(),
            })
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
        await rt["store"].async_save({"links": links})
        await rt["push"]()  # push straight away so it appears without waiting
        return self.json({"ok": True, "count": len(links)})


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

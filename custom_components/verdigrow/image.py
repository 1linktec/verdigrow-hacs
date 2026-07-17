"""VerdiGrow container photo as an HA image entity (latest attached photo)."""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import VGContainerEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    known = set()

    @callback
    def _sync():
        data = coordinator.data or {}
        new = []
        for cid, card in data.items():
            if cid not in known and card.get("image_url"):
                known.add(cid)
                new.append(VGImage(coordinator, cid, hass))
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


class VGImage(VGContainerEntity, ImageEntity):
    _attr_name = "Photo"

    def __init__(self, coordinator, cid, hass):
        VGContainerEntity.__init__(self, coordinator, cid)
        ImageEntity.__init__(self, hass)
        self._attr_unique_id = f"{DOMAIN}_container_{cid}_photo"
        self._url = (self.card or {}).get("image_url")
        self._attr_image_last_updated = dt_util.utcnow()

    @property
    def image_url(self):
        return (self.card or {}).get("image_url")

    @callback
    def _handle_coordinator_update(self):
        url = (self.card or {}).get("image_url")
        if url != self._url:
            self._url = url
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

"""Shared base for VerdiGrow container entities."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


def container_device_id(cid):
    return (DOMAIN, f"container_{cid}")


class VGContainerEntity(CoordinatorEntity):
    """An entity attached to a VerdiGrow container's HA device.

    Device name/area come from the polled card, so renaming a container in
    VerdiGrow updates HA; a container removed in VerdiGrow drops out of the
    coordinator data (its device is removed in __init__)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, cid):
        super().__init__(coordinator)
        self._cid = cid

    @property
    def card(self):
        return (self.coordinator.data or {}).get(self._cid)

    @property
    def available(self):
        return super().available and self.card is not None

    @property
    def device_info(self):
        card = self.card or {}
        info = {
            "identifiers": {container_device_id(self._cid)},
            "name": card.get("label"),
            "manufacturer": "VerdiGrow",
            "model": card.get("type"),
        }
        if card.get("area"):
            info["suggested_area"] = card["area"]
        if card.get("parent_id"):
            info["via_device"] = container_device_id(card["parent_id"])
        return info

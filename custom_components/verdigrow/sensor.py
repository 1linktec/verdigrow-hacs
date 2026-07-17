"""VerdiGrow container sensors: a 'plants' summary + one per latest metric."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import callback

from .const import DOMAIN
from .entity import VGContainerEntity

# Map VerdiGrow metric keys to HA device classes where they line up.
_DEVICE_CLASS = {
    "air_temp": "temperature", "soil_temp": "temperature",
    "humidity": "humidity", "soil_moisture": "moisture",
    "light": "illuminance", "ec": None, "ph": None,
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    known_summary = set()
    known_metric = set()

    @callback
    def _sync():
        data = coordinator.data or {}
        new = []
        for cid in data:
            if cid not in known_summary:
                known_summary.add(cid)
                new.append(VGPlantsSensor(coordinator, cid))
        for cid, card in data.items():
            for m in card.get("metrics", []):
                key = (cid, m["key"])
                if key not in known_metric:
                    known_metric.add(key)
                    new.append(VGMetricSensor(coordinator, cid, m["key"], m["name"], m["unit"]))
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()


class VGPlantsSensor(VGContainerEntity, SensorEntity):
    """State = number of plants; attributes describe what's planted + notes."""

    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator, cid):
        super().__init__(coordinator, cid)
        self._attr_unique_id = f"{DOMAIN}_container_{cid}_plants"
        self._attr_name = "Plants"

    @property
    def native_value(self):
        return (self.card or {}).get("plant_count")

    @property
    def extra_state_attributes(self):
        card = self.card or {}
        rows = []
        for o in card.get("occupancy", []):
            if o.get("plants"):
                rows.append(f"{o['label']}: " + ", ".join(
                    f"{p['variety']}×{p['count']}" if p['count'] > 1 else p['variety']
                    for p in o["plants"]))
        plants = card.get("plants", [])
        latest_note = next((p["note"] for p in plants if p.get("note")), "")
        return {
            "area": card.get("area"),
            "type": card.get("type"),
            "planted": rows,
            "plants": [p["label"] for p in plants],
            "latest_note": latest_note,
        }


class VGMetricSensor(VGContainerEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, cid, key, name, unit):
        super().__init__(coordinator, cid)
        self._key = key
        self._attr_unique_id = f"{DOMAIN}_container_{cid}_metric_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit or None
        if key in _DEVICE_CLASS and _DEVICE_CLASS[key]:
            self._attr_device_class = _DEVICE_CLASS[key]

    @property
    def native_value(self):
        for m in (self.card or {}).get("metrics", []):
            if m["key"] == self._key:
                return m["value"]
        return None

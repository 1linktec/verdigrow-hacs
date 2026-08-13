"""VerdiGrow container sensors: a 'plants' summary, plus metrics VerdiGrow owns.

**Not one entity per metric any more (#33).** A reading that arrived *from* Home
Assistant must not become a new Home Assistant entity. The entity was already there —
it is where the value came from — so re-exposing it is a pure round trip: HA writes a
value, VerdiGrow ingests it, we hand it back under another name, HA stores it a second
time. Double the throughput, and two histories describing one probe.

The same applies to readings bridged in over MQTT. A grower who points a PLC with a few
hundred tags at their broker would otherwise get a few hundred new HA entities, none of
which HA asked for.

So an entity is created only for metrics VerdiGrow is itself the origin of — manual
entries. Everything else still appears: on the Lovelace card, which reads the same
`/api/cards/` payload, and as attributes on the container's `plants` sensor, so
templates and automations can reach the values without an entity each.

The test is the reading's own `source`, which `/api/cards/` already carries, so no
server change was needed. `SensorLink` could not answer it: the Home Assistant side of
the mapping lives in *HA's* storage, not VerdiGrow's, which is why the Companion has
exactly one SensorLink row and 34k HA-sourced readings.
"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import callback

from .const import DOMAIN
from .coordinator import VerdiGrowConfigEntry
from .entity import VGContainerEntity

# Map VerdiGrow metric keys to HA device classes where they line up. Enum members
# rather than strings, so a class HA renames or drops is an ImportError in CI
# instead of a sensor that silently loses its icon and unit handling.
#
# ec and ph are absent deliberately: HA has no device class for either, and
# inventing one costs the long-term statistics that MEASUREMENT already gives them.
_DEVICE_CLASS = {
    "air_temp": SensorDeviceClass.TEMPERATURE,
    "soil_temp": SensorDeviceClass.TEMPERATURE,
    "humidity": SensorDeviceClass.HUMIDITY,
    "soil_moisture": SensorDeviceClass.MOISTURE,
    "light": SensorDeviceClass.ILLUMINANCE,
}

# Sources whose readings already exist somewhere else, so mirroring them into an HA
# entity duplicates rather than adds. See the module docstring.
MIRRORED_SOURCES = {"ha_sensor", "mqtt"}


def metric_unique_id(cid, key) -> str:
    """The unique_id a metric sensor has — or had, before #33 stopped creating some.

    One definition, used both to create entities and to find the ones a previous
    version created. Two copies of this string is how orphaned entities survive a
    cleanup that looks like it worked.
    """
    return f"{DOMAIN}_container_{cid}_metric_{key}"


@callback
def _remove_stale(hass, unique_ids) -> None:
    """Delete metric entities we no longer create.

    Registry-level removal, not just withholding the entity: an entity that is simply
    not re-created stays in the registry as "unavailable" forever, and the grower has
    to hunt them down by hand.
    """
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    for unique_id in unique_ids:
        entity_id = reg.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            reg.async_remove(entity_id)


def owns_metric(metric: dict) -> bool:
    """Whether VerdiGrow is the origin of this reading, and so should own an entity.

    Unknown or missing sources count as ours. An older Companion that doesn't report
    `source` should keep behaving as it does today — failing the other way would make
    a routine update look like every sensor had vanished.
    """
    return (metric.get("source") or "") not in MIRRORED_SOURCES


async def async_setup_entry(
    hass, entry: VerdiGrowConfigEntry, async_add_entities
) -> None:
    coordinator = entry.runtime_data.coordinator
    known_summary = set()
    known_metric = set()
    # Mirrored metrics we have already tidied up after. The cleanup is idempotent, but
    # without this it re-walks the registry for every mirrored metric on every poll,
    # forever, to do nothing.
    cleaned = set()

    @callback
    def _sync():
        data = coordinator.data or {}
        new = []
        for cid in data:
            if cid not in known_summary:
                known_summary.add(cid)
                new.append(VGPlantsSensor(coordinator, cid))
        stale = []
        for cid, card in data.items():
            for m in card.get("metrics", []):
                key = (cid, m["key"])
                if not owns_metric(m):
                    # Came from HA or MQTT: no entity. Also collect any entity an
                    # OLDER version of this integration made for it — without that,
                    # updating leaves a pile of permanently unavailable sensors,
                    # which is a worse impression than the flood was.
                    if key not in cleaned:
                        cleaned.add(key)
                        stale.append(metric_unique_id(cid, m["key"]))
                    continue
                if key not in known_metric:
                    known_metric.add(key)
                    new.append(
                        VGMetricSensor(coordinator, cid, m["key"], m["name"], m["unit"])
                    )
        if new:
            async_add_entities(new)
        if stale:
            _remove_stale(hass, stale)

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
                rows.append(
                    f"{o['label']}: "
                    + ", ".join(
                        f"{p['variety']}×{p['count']}"
                        if p["count"] > 1
                        else p["variety"]
                        for p in o["plants"]
                    )
                )
        plants = card.get("plants", [])
        latest_note = next((p["note"] for p in plants if p.get("note")), "")
        # Every metric, including ones that deliberately get no entity (#33). Without
        # this, a grower who mapped an HA sensor into a bed could not reach the value
        # from a template: the entity is gone and the card is not queryable. Keyed by
        # metric, so a template reads
        # state_attr('sensor.bed_1_plants','metrics').soil_moisture.value
        metrics = {
            m["key"]: {
                "value": m.get("value"),
                "unit": m.get("unit"),
                "name": m.get("name"),
                "at": m.get("at"),
                "source": m.get("source"),
            }
            for m in card.get("metrics", [])
        }
        return {
            "area": card.get("area"),
            "type": card.get("type"),
            "planted": rows,
            "plants": [p["label"] for p in plants],
            "latest_note": latest_note,
            "metrics": metrics,
        }


class VGMetricSensor(VGContainerEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, cid, key, name, unit):
        super().__init__(coordinator, cid)
        self._key = key
        self._attr_unique_id = metric_unique_id(cid, key)
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit or None
        if _DEVICE_CLASS.get(key):
            self._attr_device_class = _DEVICE_CLASS[key]

    @property
    def native_value(self):
        for m in (self.card or {}).get("metrics", []):
            if m["key"] == self._key:
                return m["value"]
        return None

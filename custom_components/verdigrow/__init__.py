"""
VerdiGrow — Home Assistant integration.

Phase 7 implements this. Phase 0 establishes the structure.

Design lens: VerdiGrow surfaces good per-container ENTITIES; HA renders and
controls. This integration never renders dashboards and never touches hardware.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS: list[str] = ["sensor", "binary_sensor", "image"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up VerdiGrow from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    # Phase 7: coordinator, API client, panel registration
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

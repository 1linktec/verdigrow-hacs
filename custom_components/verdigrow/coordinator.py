"""Polls VerdiGrow's /api/cards and exposes containers as HA entities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VerdiGrowAuthError, VerdiGrowError

_LOGGER = logging.getLogger(__name__)


@dataclass
class VerdiGrowData:
    """Everything one configured Companion needs at runtime.

    Lives on `entry.runtime_data`, which is the current way to hold this — it is
    typed, it dies with the entry, and it cannot be read by another integration.
    The old `hass.data[DOMAIN][entry.entry_id]` dict needed manual cleanup on
    unload, and a missed key there is a leak nothing complains about.
    """

    client: Any
    store: Store
    coordinator: VerdiGrowCoordinator
    # Pushes mapped HA sensor states to the Companion. The panel calls it directly
    # after saving a mapping, so a new sensor shows a value immediately instead of
    # looking broken until the next interval.
    push: Callable[[], Awaitable[int]]
    # Device power/energy tracking state; mutated in place by the tracker.
    dev: dict = field(default_factory=dict)


# A ConfigEntry that carries the above. Annotating with this is what makes
# `entry.runtime_data.coordinator` resolve in an editor rather than being Any.
VerdiGrowConfigEntry = ConfigEntry[VerdiGrowData]


class VerdiGrowCoordinator(DataUpdateCoordinator):
    """Fetches all containers (as cards) and keys them by id."""

    def __init__(self, hass, entry, client, interval):
        super().__init__(
            hass,
            _LOGGER,
            # Explicit, not picked up from HA's ContextVar — HA only still tolerates
            # that for custom integrations.
            config_entry=entry,
            name="VerdiGrow containers",
            update_interval=timedelta(seconds=max(300, int(interval))),
        )
        self.client = client

    async def _async_update_data(self):
        try:
            cards = await self.client.async_cards()
        except VerdiGrowAuthError as e:
            # Not UpdateFailed: retrying a rejected token forever just leaves every
            # entity unavailable with nothing on screen explaining why. This is what
            # makes HA offer "Reconfigure" when a grower rotates their API token.
            raise ConfigEntryAuthFailed(str(e)) from e
        except VerdiGrowError as e:
            raise UpdateFailed(str(e)) from e
        return {c["id"]: c for c in cards}

"""Polls VerdiGrow's /api/cards and exposes containers as HA entities."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VerdiGrowError

_LOGGER = logging.getLogger(__name__)


class VerdiGrowCoordinator(DataUpdateCoordinator):
    """Fetches all containers (as cards) and keys them by id."""

    def __init__(self, hass, client, interval):
        super().__init__(
            hass, _LOGGER, name="VerdiGrow containers",
            update_interval=timedelta(seconds=max(300, int(interval))),
        )
        self.client = client

    async def _async_update_data(self):
        try:
            cards = await self.client.async_cards()
        except VerdiGrowError as e:
            raise UpdateFailed(str(e)) from e
        return {c["id"]: c for c in cards}

"""Async client for the VerdiGrow HA-facing API (token auth)."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (API_AREAS, API_CONTAINERS, API_METRIC_TYPES, API_PING,
                    API_READINGS)

_LOGGER = logging.getLogger(__name__)


class VerdiGrowError(Exception):
    """Any VerdiGrow API failure."""


class VerdiGrowClient:
    def __init__(self, hass: HomeAssistant, url: str, token: str) -> None:
        self._session = async_get_clientsession(hass)
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _get(self, path: str) -> dict:
        try:
            async with self._session.get(self._url + path, headers=self._headers,
                                         timeout=15) as r:
                if r.status == 401:
                    raise VerdiGrowError("unauthorized (check the API token)")
                r.raise_for_status()
                return await r.json()
        except VerdiGrowError:
            raise
        except Exception as e:  # network / timeout / non-JSON
            raise VerdiGrowError(str(e)) from e

    async def async_ping(self) -> bool:
        data = await self._get(API_PING)
        return bool(data.get("ok"))

    async def async_containers(self) -> list[dict]:
        return (await self._get(API_CONTAINERS)).get("containers", [])

    async def async_areas(self) -> list[dict]:
        return (await self._get(API_AREAS)).get("areas", [])

    async def async_metric_types(self) -> list[dict]:
        return (await self._get(API_METRIC_TYPES)).get("metric_types", [])

    async def async_push(self, readings: list[dict]) -> dict:
        """POST a batch of readings. Each: {metric, value, occurred_at?, entity_id?,
        and one of container_id | container_public_id | area_id | area}."""
        if not readings:
            return {"written": 0}
        try:
            async with self._session.post(self._url + API_READINGS,
                                          json={"readings": readings},
                                          headers=self._headers, timeout=30) as r:
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            raise VerdiGrowError(str(e)) from e

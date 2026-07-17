"""Async client for the VerdiGrow HA-facing API (token auth)."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (API_AREAS, API_AREAS_IMPORT, API_CONTAINERS,
                    API_METRIC_TYPES, API_PING, API_PLANTS, API_READINGS)

_LOGGER = logging.getLogger(__name__)


class VerdiGrowError(Exception):
    """Any VerdiGrow API failure."""


class VerdiGrowClient:
    def __init__(self, hass: HomeAssistant, url: str, token: str,
                 verify_ssl: bool = True) -> None:
        # verify_ssl=False → a session that skips cert verification (self-signed
        # / internal-CA proxies that HA doesn't trust).
        self._session = async_get_clientsession(hass, verify_ssl=verify_ssl)
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _get(self, path: str) -> dict:
        try:
            async with self._session.get(self._url + path, headers=self._headers,
                                         timeout=aiohttp.ClientTimeout(total=15)) as r:
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

    async def async_plants(self) -> list[dict]:
        return (await self._get(API_PLANTS)).get("plants", [])

    async def async_areas(self) -> list[dict]:
        return (await self._get(API_AREAS)).get("areas", [])

    async def async_import_areas(self, names: list[str]) -> dict:
        """Create VerdiGrow areas from HA area names (idempotent, matched by name)."""
        try:
            async with self._session.post(
                self._url + API_AREAS_IMPORT, json={"names": names},
                headers=self._headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            raise VerdiGrowError(str(e)) from e

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
                                          headers=self._headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            raise VerdiGrowError(str(e)) from e

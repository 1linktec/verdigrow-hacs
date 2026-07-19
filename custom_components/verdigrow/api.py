"""Async client for the VerdiGrow HA-facing API (token auth)."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (API_AREAS, API_AREAS_DELETE, API_AREAS_IMPORT, API_CARDS,
                    API_CONTAINERS, API_DEVICE_MAP, API_DEVICE_USAGE, API_DEVICES,
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

    async def async_delete_area(self, area_id) -> dict:
        """Un-import a VerdiGrow area. Returns the API's JSON either way — a
        guard failure (containers/history) comes back as {"error": ...} with 400,
        NOT an exception, so the panel can show the reason."""
        try:
            async with self._session.post(
                self._url + API_AREAS_DELETE, json={"id": area_id},
                headers=self._headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
                try:
                    return await r.json()
                except Exception:  # noqa: BLE001 — non-JSON body
                    return {"error": f"HTTP {r.status}"}
        except Exception as e:
            raise VerdiGrowError(str(e)) from e

    async def async_metric_types(self) -> list[dict]:
        return (await self._get(API_METRIC_TYPES)).get("metric_types", [])

    async def async_cards(self) -> list[dict]:
        return (await self._get(API_CARDS)).get("cards", [])

    async def async_card(self, pk) -> dict:
        return await self._get(f"{API_CARDS}{pk}/")

    async def async_plant_card(self, pk) -> dict:
        return await self._get(f"{API_CARDS}plant/{pk}/")

    async def async_fetch_media(self, path: str) -> tuple[bytes | None, str | None]:
        """Fetch a media file (photo) from VerdiGrow by its path, so HA can proxy
        it same-origin (avoids mixed-content + unreachable-host in the app).
        Returns (bytes, content_type) or (None, None) on any failure."""
        try:
            async with self._session.get(self._url + path, headers=self._headers,
                                         timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    return None, None
                return (await r.read(),
                        r.headers.get("Content-Type", "application/octet-stream"))
        except Exception:  # noqa: BLE001 — image is best-effort
            return None, None

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

    async def async_devices(self) -> list[dict]:
        """Devices to track for running-cost — each with its HA entity links,
        accuracy tier and area."""
        return (await self._get(API_DEVICES)).get("devices", [])

    async def async_devices_all(self) -> list[dict]:
        """Every VerdiGrow device (for the panel's device-mapping UI)."""
        return (await self._get(API_DEVICES + "?all=1")).get("devices", [])

    async def async_device_map(self, payload: dict) -> dict:
        """Link an HA entity to a device, or create a device (action: link|create)."""
        try:
            async with self._session.post(self._url + API_DEVICE_MAP, json=payload,
                                          headers=self._headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            raise VerdiGrowError(str(e)) from e

    async def async_push_device_usage(self, usage: list[dict]) -> dict:
        """POST accumulated device usage deltas. Each item:
        {device_id, add_kwh?, add_runtime_hours?}."""
        if not usage:
            return {"updated": 0}
        try:
            async with self._session.post(self._url + API_DEVICE_USAGE,
                                          json={"usage": usage},
                                          headers=self._headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
                r.raise_for_status()
                return await r.json()
        except Exception as e:
            raise VerdiGrowError(str(e)) from e

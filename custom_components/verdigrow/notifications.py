"""Bring VerdiGrow's notifications into Home Assistant.

**A pull, and it has to be.** VerdiGrow never calls Home Assistant: a hosted Companion
lives on the internet and HA lives behind the grower's router, so a push would work on a
LAN and nowhere else. The Companion exposes `/api/notifications/?since=<id>`; this polls
it. The Companion side of this was built first and is already deployed.

**Two outputs, deliberately different in kind:**

* A **persistent notification** — visible in HA's own bell, dismissible there, and
  available on every install with nothing configured. This is the floor.
* An **event** (`verdigrow_notification`) — so a grower routes it wherever they already
  route things: phone, speaker, a light that turns red. We fire an event rather than
  calling `notify.notify` because we do not know which notifiers exist on someone's
  system, and a hardcoded service name fails *silently* on any setup that renamed it.

**`since` is what stops this being a nuisance.** Without it every poll re-announces
every open notification, and a frost warning arriving twelve times is one nobody reads.
The high-water mark is persisted, so a restart does not replay the backlog either.
"""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .api import VerdiGrowError
from .const import (
    DOMAIN,
    EVENT_NOTIFICATION,
    NOTIFY_POLL_SECONDS,
    STORAGE_KEY_NOTIFY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

# Which ones are worth interrupting someone for. The Companion already decides what to
# text; this is the HA-side equivalent, and the same reasoning applies — "AI answer
# ready" in your pocket at 11pm is how a grower turns the integration off.
_IMPORTANT = {"frost", "metric_low", "metric_high", "sensor_silent"}


class NotificationPoller:
    """Polls the Companion for new notifications and raises them in HA."""

    def __init__(self, hass: HomeAssistant, client) -> None:
        self.hass = hass
        self.client = client
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY_NOTIFY)
        self._since: int = 0
        self._unsub = None

    async def async_start(self) -> callable:
        data = await self._store.async_load() or {}
        self._since = int(data.get("since") or 0)
        # Poll once now so a grower who has just set this up sees something, then on
        # the interval. Anything already seen is filtered server-side by `since`.
        await self._async_poll()
        self._unsub = async_track_time_interval(
            self.hass, self._async_poll, timedelta(seconds=NOTIFY_POLL_SECONDS)
        )
        return self._unsub

    @callback
    def _raise(self, note: dict) -> None:
        where = note.get("container") or note.get("plant") or note.get("area") or ""
        body = note.get("body") or ""
        if where:
            body = f"{where} — {body}" if body else where

        # The event goes out for everything: a grower's automation can decide what it
        # cares about far better than we can, and filtering here would hide the ones
        # they wanted.
        self.hass.bus.async_fire(
            EVENT_NOTIFICATION,
            {
                "id": note.get("id"),
                "type": note.get("type"),
                "title": note.get("title"),
                "body": note.get("body"),
                "container": note.get("container"),
                "plant": note.get("plant"),
                "area": note.get("area"),
                "important": note.get("type") in _IMPORTANT,
            },
        )

        # The persistent notification is the visible floor, so only the ones worth
        # interrupting for. A dashboard full of "AI answer ready" trains people to
        # dismiss without reading, and then the frost warning goes with them.
        if note.get("type") in _IMPORTANT:
            persistent_notification.async_create(
                self.hass,
                body or note.get("title", ""),
                title=note.get("title") or "VerdiGrow",
                # Keyed by VerdiGrow's id: re-raising the same one replaces it rather
                # than stacking duplicates if this ever runs twice.
                notification_id=f"{DOMAIN}_{note.get('id')}",
            )

    async def _async_poll(self, _now=None) -> None:
        try:
            notes = await self.client.async_notifications(since=self._since or None)
        except VerdiGrowError as err:
            # Debug, not warning: a Companion being briefly unreachable is ordinary,
            # and a warning every five minutes during an outage is its own problem.
            _LOGGER.debug("VerdiGrow: could not fetch notifications (%s)", err)
            return

        highest = self._since
        for note in notes:
            try:
                self._raise(note)
            except Exception:
                _LOGGER.exception("VerdiGrow: failed to raise notification %s", note)
            highest = max(highest, int(note.get("id") or 0))

        if highest > self._since:
            self._since = highest
            await self._store.async_save({"since": highest})

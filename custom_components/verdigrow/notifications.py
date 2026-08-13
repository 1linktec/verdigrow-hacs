"""Bring VerdiGrow's notifications into Home Assistant.

**A pull, and it has to be.** VerdiGrow never calls Home Assistant: a hosted Companion
lives on the internet and HA lives behind the grower's router, so a push would work on a
LAN and nowhere else. The Companion exposes `/api/notifications/`; this polls it.

**Two outputs, deliberately different in kind:**

* A **persistent notification** — visible in HA's own bell, dismissible there, and
  available on every install with nothing configured. This is the floor.
* An **event** (`verdigrow_notification`) — so a grower routes it wherever they already
  route things: phone, speaker, a light that turns red. We fire an event rather than
  calling `notify.notify` because we do not know which notifiers exist on someone's
  system, and a hardcoded service name fails *silently* on any setup that renamed it.

**We poll the whole open set, and clear what is no longer in it.** An earlier version
asked for `?since=<id>` and only ever *created* notifications, which is wrong in a way
that matters for chores: water the bucket, the Companion resolves the reminder, and HA
would still be showing "water Bucket 1" until the grower dismissed it by hand. A
reminder you have to clear twice is worse than none. The same bug left frost warnings up
after the night had passed.

So the ids we have announced are tracked instead of a high-water mark. Anything open
and not yet announced gets raised; anything announced and no longer open gets
dismissed. The set is self-pruning — it can only hold what is currently open — and it
is persisted, so a restart neither replays the backlog nor forgets what to clear.
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

# Which ones get a persistent notification. The Companion makes the same call about
# what is worth a text, and the reasoning carries: "AI answer ready" in HA's bell at
# 11pm is how a grower learns to dismiss without reading, and the frost warning goes
# with it.
#
# `watering` is in the list because a grower only gets one by explicitly setting an
# interval on a container — they asked to be reminded, and a reminder that requires
# writing an automation first is not one. It is safe to include precisely because these
# now clear themselves when the Companion resolves them.
_IMPORTANT = {"frost", "metric_low", "metric_high", "sensor_silent", "watering"}


class NotificationPoller:
    """Polls the Companion for notifications and keeps HA's bell in step with it."""

    def __init__(self, hass: HomeAssistant, client) -> None:
        self.hass = hass
        self.client = client
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY_NOTIFY)
        # Companion notification ids we have already announced.
        self._announced: set[int] = set()
        self._legacy_since = 0
        self._unsub = None

    async def async_start(self) -> callable:
        data = await self._store.async_load() or {}
        self._announced = {int(i) for i in data.get("announced", [])}
        # Upgrade from the high-water-mark version: treat everything at or below the
        # stored mark as already announced, so this does not replay the backlog once.
        self._legacy_since = int(data.get("since") or 0)
        # Poll once now so a grower who has just set this up sees something, then on
        # the interval.
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

        if note.get("type") in _IMPORTANT:
            persistent_notification.async_create(
                self.hass,
                body or note.get("title", ""),
                title=note.get("title") or "VerdiGrow",
                notification_id=self._notification_id(note.get("id")),
            )

    def _notification_id(self, note_id) -> str:
        """Keyed by VerdiGrow's own id, which is what lets us find it again to clear."""
        return f"{DOMAIN}_{note_id}"

    @callback
    def _clear(self, note_id: int) -> None:
        persistent_notification.async_dismiss(self.hass, self._notification_id(note_id))

    async def _async_poll(self, _now=None) -> None:
        try:
            notes = await self.client.async_notifications()
        except VerdiGrowError as err:
            # Debug, not warning: a Companion being briefly unreachable is ordinary,
            # and a warning every five minutes during an outage is its own problem.
            # Crucially we return WITHOUT clearing anything — an unreachable Companion
            # is not evidence that a frost warning has stopped applying.
            _LOGGER.debug("VerdiGrow: could not fetch notifications (%s)", err)
            return

        open_ids = {int(n["id"]) for n in notes if n.get("id") is not None}
        before = set(self._announced)

        for note in notes:
            note_id = note.get("id")
            if note_id is None or int(note_id) in self._announced:
                continue
            if int(note_id) <= self._legacy_since:
                self._announced.add(int(note_id))  # pre-upgrade; already seen
                continue
            try:
                self._raise(note)
            except Exception:
                _LOGGER.exception("VerdiGrow: failed to raise notification %s", note)
            self._announced.add(int(note_id))

        # Dealt with in the Companion — watered, resolved, or dismissed there. Take it
        # off HA's bell too, so the grower does not clear the same thing twice.
        for gone in self._announced - open_ids:
            self._clear(gone)

        self._announced &= open_ids
        if self._announced != before:
            await self._store.async_save({"announced": sorted(self._announced)})

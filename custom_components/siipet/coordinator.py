"""Data coordinator for the SiiPet integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AbnormalLabels,
    Camera,
    Cat,
    DaySummary,
    DayVisits,
    SiiPetAuthError,
    SiiPetClient,
    SiiPetError,
    Visit,
)
from .const import (
    DOMAIN,
    LABELS_INTERVAL,
    MIDNIGHT_GRACE,
    PAST_DAY_INTERVAL,
    SYNC_INTERVAL,
    UNKNOWN_CAT_ID,
    UPDATE_INTERVAL,
    WINDOW_DAYS,
)

if TYPE_CHECKING:
    from .calendar_data import SiiPetCalendar
    from .device_state import SiiPetDeviceCoordinator
    from .media import SiiPetMedia
    from .media_mirror import SiiPetMirror

_LOGGER = logging.getLogger(__name__)

# Scheduler jitter can end the twelfth update a moment before an hour has
# passed. Half an update of tolerance keeps an hourly read on that update.
DUE_TOLERANCE = UPDATE_INTERVAL / 2


@dataclass(slots=True)
class SiiPetRuntime:
    """Objects that live for as long as the config entry is loaded."""

    client: SiiPetClient
    coordinator: SiiPetCoordinator
    media: SiiPetMedia
    calendar: SiiPetCalendar
    device_state: SiiPetDeviceCoordinator
    mirror: SiiPetMirror | None = None


type SiiPetConfigEntry = ConfigEntry[SiiPetRuntime]


@dataclass(frozen=True, slots=True)
class SiiPetData:
    """A snapshot of the account for entities."""

    cats: Mapping[str, Cat]
    cameras: Mapping[str, Camera]
    days: Mapping[date, tuple[Visit, ...]]
    summaries: Mapping[str, DaySummary]
    labels: AbnormalLabels
    today: date
    new_visits: tuple[Visit, ...]
    more: bool
    updated_at: datetime

    def cat_ids(self, visit: Visit) -> tuple[str, ...]:
        """Return the known cats of a visit, or the Unknown cat."""
        known = tuple(pet_id for pet_id in visit.pet_ids if pet_id in self.cats)
        return known or (UNKNOWN_CAT_ID,)

    def visits(self, cat_id: str, day: date | None = None) -> list[Visit]:
        """Return the visits of a cat on one day, or in the whole window."""
        days = [day] if day is not None else sorted(self.days)
        return [
            visit
            for current in days
            for visit in self.days.get(current, ())
            if cat_id in self.cat_ids(visit)
        ]


class SiiPetCoordinator(DataUpdateCoordinator[SiiPetData]):
    """Poll the SiiPet cloud and keep a 7-day window of visits."""

    config_entry: SiiPetConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: SiiPetConfigEntry, client: SiiPetClient
    ) -> None:
        """Create the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self._cats: dict[str, Cat] = {}
        self._cameras: dict[str, Camera] = {}
        self._labels = AbnormalLabels()
        self._days: dict[date, DayVisits] = {}
        # These times are in UTC. Local times that share a time zone subtract
        # without the offset change, so an interval would be off by an hour
        # across a DST change.
        self._read_at: dict[date, datetime] = {}
        self._synced_at: datetime | None = None
        self._labels_at: datetime | None = None
        self._labels_failed_at: datetime | None = None
        self._labels_warned = False
        self._unknown_refs: set[str] = set()
        self._seen: set[str] | None = None
        self._warned_more = False
        # A regular update that read a day before an edit or a delete must not
        # store that day after the day refresh. A stale day can bring back a
        # deleted visit, and the next snapshot then reports it as new.
        self._lock = asyncio.Lock()

    async def _async_update_data(self) -> SiiPetData:
        async with self._lock:
            now = dt_util.now()
            today = now.date()
            try:
                await self._async_refresh_window(now, today)
            except SiiPetAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except SiiPetError as err:
                raise UpdateFailed(str(err)) from err
            return self._snapshot(today, now)

    async def async_refresh_day(self, day: date) -> None:
        """Read one day of the window again and update the listeners."""
        async with self._lock:
            if day not in self._days:
                return
            now = dt_util.now()
            today = now.date()
            until = now.time() if day == today else None
            try:
                visits = await self.client.get_day(day, until=until)
            except SiiPetError as err:
                _LOGGER.warning("Could not read the visits of %s again: %s", day, err)
                # The next regular update reads the day again.
                self._read_at.pop(day, None)
                return
            self._store(day, visits, now)
            self.async_set_updated_data(self._snapshot(today, now))

    async def _async_refresh_window(self, now: datetime, today: date) -> None:
        synced = False
        if _due(self._synced_at, SYNC_INTERVAL, now):
            await self._async_sync(now)
            synced = True
        if self._labels_due(now):
            await self._async_read_labels(now)

        self._store(today, await self.client.get_day(today, until=now.time()), now)
        for offset in range(1, WINDOW_DAYS):
            day = today - timedelta(days=offset)
            if not self._past_day_due(day, today, now):
                continue
            first_read = day not in self._days
            try:
                visits = await self.client.get_day(day)
            except SiiPetAuthError:
                raise
            except SiiPetError as err:
                _LOGGER.warning("Could not read the visits of %s: %s", day, err)
                continue
            self._store(day, visits, now)
            if first_read and self._seen is not None:
                # A past day read for the first time (a failed first update,
                # or an outage) is not new. Seed it as seen so its visits do
                # not burst into new_visits.
                self._seen.update(visit.event_id for visit in visits.visits)

        oldest = today - timedelta(days=WINDOW_DAYS - 1)
        for day in [day for day in self._days if day < oldest]:
            del self._days[day]
            self._read_at.pop(day, None)

        unknown = self._new_unknown_refs()
        if unknown:
            # Sync once per new id. An id that stays unknown after a
            # successful sync is not retried.
            if not synced:
                await self._async_sync(now)
            self._unknown_refs |= unknown

    async def _async_sync(self, now: datetime) -> None:
        self._cats = await self.client.get_cats()
        self._cameras = await self.client.get_cameras()
        self._synced_at = dt_util.as_utc(now)

    def _labels_due(self, now: datetime) -> bool:
        if self._labels_failed_at is not None:
            return _due(self._labels_failed_at, SYNC_INTERVAL, now)
        return _due(self._labels_at, LABELS_INTERVAL, now)

    async def _async_read_labels(self, now: datetime) -> None:
        try:
            self._labels = await self.client.get_abnormal_labels()
        except SiiPetAuthError:
            raise
        except SiiPetError as err:
            if self._labels_warned:
                _LOGGER.debug("Could not read the abnormal labels: %s", err)
            else:
                _LOGGER.warning("Could not read the abnormal labels: %s", err)
                self._labels_warned = True
            self._labels_failed_at = dt_util.as_utc(now)
            return
        self._labels_at = dt_util.as_utc(now)
        self._labels_failed_at = None
        self._labels_warned = False

    def _past_day_due(self, day: date, today: date, now: datetime) -> bool:
        read_at = self._read_at.get(day)
        if read_at is None:
            return True
        if day == today - timedelta(days=1):
            since_midnight = now - dt_util.start_of_local_day(now)
            if since_midnight < MIDNIGHT_GRACE:
                return True
        return _due(read_at, PAST_DAY_INTERVAL, now)

    def _store(self, day: date, visits: DayVisits, now: datetime) -> None:
        self._days[day] = visits
        self._read_at[day] = dt_util.as_utc(now)
        if visits.more and not self._warned_more:
            self._warned_more = True
            _LOGGER.warning(
                "The visit list of %s has more pages. Paging is not supported, "
                "so visit counts can be too low",
                day,
            )

    def _new_unknown_refs(self) -> set[str]:
        refs: set[str] = set()
        for visits in self._days.values():
            for visit in visits.visits:
                refs.update(p for p in visit.pet_ids if p not in self._cats)
                if visit.sn and visit.sn not in self._cameras:
                    refs.add(visit.sn)
        return refs - self._unknown_refs

    def _snapshot(self, today: date, now: datetime) -> SiiPetData:
        days = {day: visits.visits for day, visits in self._days.items()}
        current = {
            visit.event_id: visit for visits in days.values() for visit in visits
        }
        if self._seen is None:
            new: tuple[Visit, ...] = ()
        else:
            new = tuple(
                sorted(
                    (visit for key, visit in current.items() if key not in self._seen),
                    key=lambda visit: visit.start,
                )
            )
        self._seen = set(current)
        today_visits = self._days.get(today)
        return SiiPetData(
            cats=dict(self._cats),
            cameras=dict(self._cameras),
            days=days,
            summaries=dict(today_visits.summaries) if today_visits else {},
            labels=self._labels,
            today=today,
            new_visits=new,
            more=any(visits.more for visits in self._days.values()),
            updated_at=now,
        )


def _due(last: datetime | None, interval: timedelta, now: datetime) -> bool:
    """Return True when `interval` passed since `last`, a time in UTC."""
    if last is None:
        return True
    return dt_util.as_utc(now) - last >= interval - DUE_TOLERANCE

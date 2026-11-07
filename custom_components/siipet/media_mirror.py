"""Keep a local copy of recent SiiPet media: queue, download, check, and clean up."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import logging

import aiohttp
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .api import Visit
from .const import DOMAIN
from .coordinator import SiiPetConfigEntry, SiiPetCoordinator, SiiPetData
from .media import MediaCredentialsError, MediaError, SiiPetMedia
from .media_store import (
    UNKNOWN_SIZE_ALLOWANCE,
    MediaCheckFailed,
    MediaDiskFull,
    MediaFile,
    MediaStore,
    MediaStoreError,
    safe_id,
    visit_day,
)

_LOGGER = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=60)
CHUNK_SIZE = 1024 * 1024
MIN_FREE_BYTES = 1024**3
RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=24),
)
ISSUE_DISK_FULL = "media_disk_full"
ISSUE_FOLDER = "media_folder_unavailable"
AVATAR = "avatar"
# Orders the files of one visit, small files first, so the card gets its
# images before the recording.
_RANK = {MediaFile.COVER: 2, MediaFile.STOOL: 1, MediaFile.RECORDING: 0}
_EPOCH = datetime.fromtimestamp(0, UTC)

type _JobKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _Job:
    """One file to download. `kind` is None for a cat avatar."""

    kind: MediaFile | None
    item_id: str
    key: str
    size: int | None = None
    md5: str | None = None
    day: date | None = None
    start: datetime | None = None

    @property
    def job_key(self) -> _JobKey:
        return (self.item_id, self.kind or AVATAR)

    @property
    def label(self) -> str:
        if self.kind is None:
            return "avatar"
        if self.kind is MediaFile.RECORDING:
            return "recording"
        return f"{self.kind} image"

    @property
    def order(self) -> tuple[bool, datetime, int]:
        """Avatars first, then the newest visit, then its smaller files."""
        rank = _RANK[self.kind] if self.kind else 0
        return (self.kind is None, self.start or _EPOCH, rank)


@dataclass(frozen=True, slots=True)
class _Failure:
    """A failed job, kept so a later update can try it again."""

    job: _Job
    attempts: int
    retry_at: datetime


def _visit_jobs(visit: Visit, day: date) -> list[_Job]:
    video_key = visit.video_key if visit.cloud_stored else None
    files = (
        (MediaFile.COVER, visit.cover_key, visit.cover_size, None),
        (MediaFile.STOOL, visit.stool_key, visit.stool_size, None),
        (MediaFile.RECORDING, video_key, visit.video_size, visit.video_md5),
    )
    return [
        _Job(kind, visit.event_id, key, size, md5, day, visit.start)
        for kind, key, size, md5 in files
        if key
    ]


@callback
def async_raise_issue(
    hass: HomeAssistant, entry: SiiPetConfigEntry, issue_id: str
) -> None:
    """Show a repair issue of the local media copy. It goes with the entry."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        config_entry_id=entry.entry_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=issue_id,
    )


@callback
def async_clear_issues(hass: HomeAssistant) -> None:
    """Remove the repair issues of the local media copy."""
    for issue_id in (ISSUE_DISK_FULL, ISSUE_FOLDER):
        ir.async_delete_issue(hass, DOMAIN, issue_id)


class SiiPetMirror:
    """Copy the media of the last `days` days into the store, one file at a time.

    A worker task runs while files wait, and a new update starts it again.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SiiPetConfigEntry,
        coordinator: SiiPetCoordinator,
        media: SiiPetMedia,
        store: MediaStore,
        days: int,
    ) -> None:
        """Create the mirror of one entry. Call `async_start` to run it."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.media = media
        self.store = store
        self.days = days
        self._pending: dict[_JobKey, _Job] = {}
        self._failures: dict[_JobKey, _Failure] = {}
        self._worker: asyncio.Task[None] | None = None
        self._stopped = False
        self._disk_full = False
        # Set when the disk is full or the credentials fail. The queue then
        # waits for the next update.
        self._paused = False
        self._active: _JobKey | None = None
        # Deleted visits, with the day of the delete. S3 keeps the files after
        # a delete, so a day read that started before it can return the visit.
        self._deleted: dict[str, date] = {}

    async def async_start(self) -> None:
        """Clean up, queue the missing media, and start the downloads."""
        await self._async_cleanup()
        self.entry.async_on_unload(self._async_unload)
        self.entry.async_on_unload(
            self.coordinator.async_add_listener(self._async_on_update)
        )
        self.entry.async_on_unload(
            async_track_time_change(
                self.hass, self._async_daily_trigger, hour=0, minute=5, second=0
            )
        )
        await self._async_update()
        self.entry.async_create_background_task(
            self.hass, self._async_backfill(), "siipet media backfill"
        )

    @callback
    def _async_unload(self) -> None:
        """Stop queueing new downloads. The entry cancels the background tasks."""
        self._stopped = True
        self._pending.clear()

    async def async_forget(self, event_id: str) -> None:
        """Delete the files of a visit, and keep it out of the copy from now on."""
        self._deleted[event_id] = dt_util.now().date()
        for job_key in [job_key for job_key in self._pending if job_key[0] == event_id]:
            del self._pending[job_key]
        self._failures = {
            job_key: failure
            for job_key, failure in self._failures.items()
            if job_key[0] != event_id
        }
        await self.store.async_delete_visit(event_id)

    def stats(self) -> dict[str, int]:
        """Return the numbers of waiting and failing downloads."""
        return {"queued": len(self._pending), "failing": len(self._failures)}

    @property
    def running(self) -> bool:
        """Return False once the copy has stopped or the entry has unloaded."""
        return not self._stopped

    def _in_window(self, day: date) -> bool:
        today = dt_util.now().date()
        return today - timedelta(days=self.days - 1) <= day <= today

    @callback
    def _async_on_update(self) -> None:
        self.entry.async_create_background_task(
            self.hass, self._async_update(), "siipet media update"
        )

    async def _async_update(self) -> None:
        """Delete the stored files that changed, and queue the missing ones."""
        data = self.coordinator.data
        await self._async_delete_changed(data)
        self._paused = False
        self._queue_data(data)

    async def _async_delete_changed(self, data: SiiPetData) -> None:
        """Delete the stored files that the polled days no longer match.

        A file goes when its key left the data or its size changed. The files
        in the folder of a polled day go when no polled day lists their visit.
        """
        listed: set[str] = set()
        for visits in data.days.values():
            for visit in visits:
                listed.add(visit.event_id)
                if stale := self._stale_files(visit):
                    await self.store.async_delete_visit(visit.event_id, stale)
        if data.more:
            # A day list with more pages can leave out a visit that exists.
            return
        for day in data.days:
            for event_id in self.store.visit_ids(day) - listed:
                await self.store.async_delete_visit(event_id)

    def _stale_files(self, visit: Visit) -> list[MediaFile]:
        """Return the stored files of a visit with no key or with a new size."""
        sizes = {job.kind: job.size for job in _visit_jobs(visit, visit_day(visit))}
        return [
            kind
            for kind in MediaFile
            if (stored := self.store.size(kind, visit.event_id)) is not None
            and (kind not in sizes or sizes[kind] not in (None, stored))
        ]

    def _queue_data(self, data: SiiPetData) -> None:
        # The current data goes first, so a fresh avatar key or a changed
        # visit size or hash is not shadowed by a stale retry of the same slot.
        for cat in data.cats.values():
            if (
                cat.avatar_key
                and self.store.avatar_path(cat.pet_id, cat.avatar_key) is None
            ):
                self._add(_Job(None, cat.pet_id, cat.avatar_key))
        for visits in data.days.values():
            self._queue_visits(visits)
        self._retry_failures()
        self._kick()

    def _queue_visits(self, visits: Iterable[Visit]) -> None:
        for visit in visits:
            day = visit_day(visit)
            if not self._in_window(day):
                continue
            for job in _visit_jobs(visit, day):
                assert job.kind is not None
                if self.store.path(job.kind, job.item_id) is None:
                    self._add(job)

    def _retry_failures(self) -> None:
        """Add again the failed jobs of an unpolled day whose wait is over.

        The current data decides what to queue for a polled day and for the
        avatars, so their failures are not retried from their own records.
        """
        now = dt_util.utcnow()
        polled_days = self.coordinator.data.days
        for failure in list(self._failures.values()):
            job = failure.job
            if (
                job.kind is not None
                and job.day not in polled_days
                and job.job_key not in self._pending
                and failure.retry_at <= now
                and not self._should_skip(job)
            ):
                self._add(job)

    def _should_skip(self, job: _Job) -> bool:
        """True when a job's file is already stored, or its day left the window."""
        if job.day is not None and not self._in_window(job.day):
            return True
        return self._is_stored(job)

    def _is_stored(self, job: _Job) -> bool:
        if job.kind is None:
            return self.store.avatar_path(job.item_id, job.key) is not None
        return self.store.path(job.kind, job.item_id) is not None

    def _add(self, job: _Job) -> None:
        if (
            self._stopped
            or not safe_id(job.item_id)
            or job.job_key == self._active
            or (job.kind is not None and job.item_id in self._deleted)
        ):
            return
        failure = self._failures.get(job.job_key)
        if failure is not None:
            same = (failure.job.key, failure.job.size, failure.job.md5)
            if same != (job.key, job.size, job.md5):
                # The current data moved on from what failed, so the old
                # backoff does not apply to it.
                del self._failures[job.job_key]
            elif failure.retry_at > dt_util.utcnow():
                return
        self._pending[job.job_key] = job

    @callback
    def _kick(self) -> None:
        if self._stopped or self._paused or not self._pending:
            return
        if self._worker is None or self._worker.done():
            self._worker = self.entry.async_create_background_task(
                self.hass, self._async_run(), "siipet media downloads"
            )

    def _next_job(self) -> _Job | None:
        while self._pending:
            job = max(self._pending.values(), key=lambda job: job.order)
            del self._pending[job.job_key]
            if self._should_skip(job):
                continue
            self._active = job.job_key
            return job
        return None

    async def _async_run(self) -> None:
        while (job := self._next_job()) is not None:
            try:
                ready = await self._async_has_room(job)
                done = ready and await self._async_download(job)
            finally:
                self._active = None
            if not done:
                # The job waits with the rest of the queue for the next update.
                self._add(job)
                self._paused = True
                return

    async def _async_has_room(self, job: _Job) -> bool:
        try:
            free = await self.store.async_free_bytes()
        except MediaStoreError as err:
            self._stop(err)
            return False
        size = UNKNOWN_SIZE_ALLOWANCE if job.size is None else job.size
        if free - size < MIN_FREE_BYTES:
            self._pause_disk_full()
            return False
        if self._disk_full:
            self._disk_full = False
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_DISK_FULL)
        return True

    def _pause_disk_full(self) -> None:
        if not self._disk_full:
            _LOGGER.warning("SiiPet paused the local media copy: the disk is full")
            self._disk_full = True
        async_raise_issue(self.hass, self.entry, ISSUE_DISK_FULL)

    async def _async_download(self, job: _Job) -> bool:
        """Download one file. Return False when the run has to stop."""
        try:
            async with self.media.async_open(
                job.key, job.label, DOWNLOAD_TIMEOUT
            ) as response:
                chunks = response.content.iter_chunked(CHUNK_SIZE)
                if job.kind is None:
                    await self.store.async_write_avatar(
                        job.item_id, job.key, chunks, size=job.size
                    )
                else:
                    day = job.day
                    assert day is not None
                    await self.store.async_write(
                        job.kind,
                        job.item_id,
                        day,
                        chunks,
                        size=job.size,
                        md5=job.md5,
                        keep=lambda: (
                            self._in_window(day) and job.item_id not in self._deleted
                        ),
                    )
        except MediaDiskFull:
            self._pause_disk_full()
            return False
        except MediaStoreError as err:
            self._stop(err)
            return False
        except MediaCredentialsError as err:
            # The coordinator starts a reauth when the sign-in has ended.
            _LOGGER.debug("SiiPet paused the local media copy: %s", err)
            return False
        except (MediaError, MediaCheckFailed) as err:
            self._fail(job, err)
        except Exception as err:
            # A download error of an unknown shape must not end the worker.
            # Its message and its traceback can hold a signed URL or a media
            # key, so the log names only its type.
            self._record_failure(job)
            _LOGGER.error(
                "The local media copy hit an unexpected error (%s)",
                type(err).__name__,
            )
        else:
            self._failures.pop(job.job_key, None)
        return True

    def _record_failure(self, job: _Job) -> None:
        if job.kind is not None and job.item_id in self._deleted:
            # The visit is gone, so a retry must not bring its files back.
            return
        failure = self._failures.get(job.job_key)
        attempts = failure.attempts + 1 if failure else 1
        delay = RETRY_DELAYS[min(attempts, len(RETRY_DELAYS)) - 1]
        self._failures[job.job_key] = _Failure(job, attempts, dt_util.utcnow() + delay)

    def _fail(self, job: _Job, err: Exception) -> None:
        self._record_failure(job)
        _LOGGER.debug("A SiiPet %s download failed: %s", job.label, err)

    def _stop(self, err: MediaStoreError) -> None:
        _LOGGER.warning("SiiPet stopped the local media copy: %s", err)
        self._stopped = True
        self._pending.clear()
        async_raise_issue(self.hass, self.entry, ISSUE_FOLDER)

    async def _async_backfill(self) -> None:
        """Queue the missing media of every day in the window."""
        today = dt_util.now().date()
        for offset in range(self.days):
            if self._stopped:
                return
            try:
                visits = await self.media.async_day_visits(
                    today - timedelta(days=offset)
                )
            except MediaError as err:
                _LOGGER.debug("SiiPet skipped a day of the local media copy: %s", err)
                continue
            self._queue_visits(visits)
            self._kick()

    @callback
    def _async_daily_trigger(self, now: datetime) -> None:
        self.entry.async_create_background_task(
            self.hass, self._async_daily(), "siipet media daily"
        )

    async def _async_daily(self) -> None:
        await self._async_cleanup()
        await self._async_backfill()

    async def _async_cleanup(self) -> None:
        cutoff = dt_util.now().date() - timedelta(days=self.days - 1)
        current_cats = self.coordinator.data.cats
        try:
            await self.store.async_delete_before(cutoff)
            await self.store.async_prune_avatars(
                {cat.pet_id: cat.avatar_key for cat in current_cats.values()}
            )
        except MediaStoreError as err:
            self._stop(err)
            return
        self._failures = {
            job_key: failure
            for job_key, failure in self._failures.items()
            if (failure.job.day is not None and failure.job.day >= cutoff)
            or (failure.job.day is None and failure.job.item_id in current_cats)
        }
        self._pending = {
            job_key: job
            for job_key, job in self._pending.items()
            if job.day is None or job.day >= cutoff
        }
        # A visit is never later than the day of its delete, so a delete
        # before the window has no visit left to keep out.
        self._deleted = {
            event_id: deleted_on
            for event_id, deleted_on in self._deleted.items()
            if deleted_on >= cutoff
        }

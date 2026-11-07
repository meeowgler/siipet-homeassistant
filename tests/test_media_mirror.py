"""Tests for the local copy of SiiPet media."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
import errno
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.siipet.api import SiiPetConnectionError
from custom_components.siipet.const import DOMAIN
from custom_components.siipet.media_mirror import (
    ISSUE_DISK_FULL,
    ISSUE_FOLDER,
    MIN_FREE_BYTES,
)
from custom_components.siipet.media_store import (
    UNKNOWN_SIZE_ALLOWANCE,
    MediaStoreError,
    key_hash,
)

from .common import (
    COVER,
    S3,
    STOOL,
    TODAY,
    VIDEO,
    day_folder,
    fixture_day,
    md5_hex,
    mirror_visit,
    mock_s3,
    s3_gets,
    serve_days,
    setup_mirror,
)


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)


def _put(path: Path, data: bytes) -> None:
    """Write a file for a test, with its folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_new_visit_media_is_stored(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """The recording, the cover, the stool photo, and the avatars land on disk."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    folder = day_folder(media_dir)
    assert (folder / "ev-1.mp4").read_bytes() == VIDEO
    assert (folder / "ev-1.cover.jpg").read_bytes() == COVER
    assert (folder / "ev-1.stool.jpg").read_bytes() == STOOL
    avatars = media_dir / ".siipet" / "avatars"
    assert (avatars / f"pet-luna.{key_hash('resources/luna.jpg')}.jpg").exists()
    assert (avatars / f"pet-milo.{key_hash('resources/milo.jpg')}.jpg").exists()


async def test_default_is_seven_days(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """An entry without the option keeps 7 days."""
    old = mirror_visit(event_id="ev-8", start=mirror_visit().start - timedelta(days=7))
    week = mirror_visit(event_id="ev-7", start=mirror_visit().start - timedelta(days=6))
    serve_days(
        mock_client,
        {
            TODAY: (mirror_visit(),),
            TODAY - timedelta(days=6): (week,),
            TODAY - timedelta(days=7): (old,),
        },
    )
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, None)
    assert (day_folder(media_dir) / "ev-1.mp4").exists()
    assert (day_folder(media_dir, TODAY - timedelta(days=6)) / "ev-7.mp4").exists()
    assert not day_folder(media_dir, TODAY - timedelta(days=7)).exists()


async def test_zero_days_deletes_the_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """With 0 days, the setup deletes the folder and downloads nothing."""
    _put(day_folder(media_dir) / "ev-1.mp4", VIDEO)
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 0)
    assert not (media_dir / ".siipet").exists()
    assert aioclient_mock.call_count == 0
    assert config_entry.runtime_data.mirror is None


async def test_backfill_reads_days_before_the_coordinator_window(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A day older than the 7 polled days comes from its own day read."""
    old_day = TODAY - timedelta(days=9)
    old = mirror_visit(start=mirror_visit().start - timedelta(days=9))
    serve_days(mock_client, {old_day: (old,)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 10)
    assert (day_folder(media_dir, old_day) / "ev-1.mp4").read_bytes() == VIDEO


async def test_visit_outside_the_window_is_not_stored(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """With 1 day, a visit of yesterday stays in the cloud."""
    old = mirror_visit(start=mirror_visit().start - timedelta(days=1))
    serve_days(mock_client, {TODAY - timedelta(days=1): (old,)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 1)
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 0
    assert not day_folder(media_dir, TODAY - timedelta(days=1)).exists()


async def test_wrong_hash_waits_before_the_next_try(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A recording with a wrong MD5 is not stored and waits 5 minutes."""
    serve_days(mock_client, {TODAY: (mirror_visit(video_md5=md5_hex(b"other")),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert not (day_folder(media_dir) / "ev-1.mp4").exists()
    assert (day_folder(media_dir) / "ev-1.cover.jpg").exists()
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1

    frozen_time.tick(timedelta(minutes=1))
    await _refresh(hass, config_entry)
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1

    frozen_time.tick(timedelta(minutes=5))
    await _refresh(hass, config_entry)
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 2


async def test_403_renews_the_credentials(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """After a 403, the download signs again with new credentials."""
    statuses = [403, 200]

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(
            method, url, status=statuses.pop(0), response=VIDEO
        )

    serve_days(mock_client, {TODAY: (mirror_visit(cover_key=None, stool_key=None),)})
    aioclient_mock.get(S3 + "events/ev-1/video.mp4", side_effect=respond)
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert (day_folder(media_dir) / "ev-1.mp4").read_bytes() == VIDEO
    assert mock_client.get_media_credentials.await_count == 2


async def test_unfinished_upload_is_stored_later(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A visit without its cloud recording gets it on a later update."""
    serve_days(mock_client, {TODAY: (mirror_visit(cloud_stored=False),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert (day_folder(media_dir) / "ev-1.cover.jpg").exists()
    assert not (day_folder(media_dir) / "ev-1.mp4").exists()

    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    await _refresh(hass, config_entry)
    assert (day_folder(media_dir) / "ev-1.mp4").read_bytes() == VIDEO


async def test_low_disk_space_stops_the_copy_and_raises_an_issue(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """Below 1 GB of free space, nothing downloads until space returns."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    with patch(
        "custom_components.siipet.media_store.shutil.disk_usage",
        return_value=SimpleNamespace(free=MIN_FREE_BYTES - 1),
    ):
        await setup_mirror(hass, config_entry, 7)
    assert aioclient_mock.call_count == 0
    assert _issue(hass, ISSUE_DISK_FULL).config_entry_id == config_entry.entry_id

    await _refresh(hass, config_entry)
    assert (day_folder(media_dir) / "ev-1.mp4").exists()
    assert _issue(hass, ISSUE_DISK_FULL) is None


async def test_folder_that_cannot_be_written_raises_an_issue(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A folder that cannot be created leaves the entry loaded, with an issue."""
    _put(media_dir / ".siipet", b"a file, not a folder")
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.mirror is None
    assert _issue(hass, ISSUE_FOLDER) is not None
    assert aioclient_mock.call_count == 0


async def test_no_local_media_folder_raises_an_issue(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    """Without a local media folder in Home Assistant, the copy stays off."""
    hass.config.media_dirs = {}
    await setup_mirror(hass, config_entry, 7)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.mirror is None
    assert _issue(hass, ISSUE_FOLDER) is not None


async def test_a_later_setup_clears_the_folder_issue(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The folder issue goes when the folder works again."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_FOLDER,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_FOLDER,
    )
    serve_days(mock_client, {})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert _issue(hass, ISSUE_FOLDER) is None


async def test_issues_go_with_the_entry(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
) -> None:
    """A media copy issue belongs to the entry, so it goes when the entry goes."""
    hass.config.media_dirs = {}
    await setup_mirror(hass, config_entry, 7)
    assert _issue(hass, ISSUE_FOLDER).config_entry_id == config_entry.entry_id

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, ISSUE_FOLDER) is None


async def test_daily_cleanup_deletes_days_that_left_the_window(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """The setup and the daily run at 00:05 delete day folders before the window."""
    for offset in (1, 2):
        folder = day_folder(media_dir, TODAY - timedelta(days=offset))
        _put(folder / f"ev-old-{offset}.mp4", b"old")
    serve_days(mock_client, {})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 2)
    assert day_folder(media_dir, TODAY - timedelta(days=1)).exists()
    assert not day_folder(media_dir, TODAY - timedelta(days=2)).exists()

    next_run = datetime.fromisoformat("2026-09-27T00:05:00+00:00")
    frozen_time.move_to(next_run)
    async_fire_time_changed(hass, next_run)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not day_folder(media_dir, TODAY - timedelta(days=1)).exists()


async def test_download_that_ends_after_midnight_is_dropped(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A file whose day leaves the window during its download is not kept."""
    # Local midnight in Tokyo comes before the fixture credentials expire.
    await hass.config.async_set_time_zone("Asia/Tokyo")
    frozen_time.move_to("2026-09-26T14:59:59+00:00")

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        frozen_time.move_to("2026-09-26T15:00:01+00:00")
        return AiohttpClientMockResponse(method, url, response=VIDEO)

    serve_days(mock_client, {TODAY: (mirror_visit(cover_key=None, stool_key=None),)})
    aioclient_mock.get(S3 + "events/ev-1/video.mp4", side_effect=respond)
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 1)
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1
    assert not (day_folder(media_dir) / "ev-1.mp4").exists()


async def test_new_avatar_key_replaces_the_avatar(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A cat with a new avatar gets the new file, and the old one goes."""
    serve_days(mock_client, {})
    mock_s3(aioclient_mock, **{"resources/luna-2.jpg": b"luna-2"})
    await setup_mirror(hass, config_entry, 7)
    avatars = media_dir / ".siipet" / "avatars"
    old = avatars / f"pet-luna.{key_hash('resources/luna.jpg')}.jpg"
    assert old.exists()

    cats = dict(mock_client.get_cats.return_value)
    cats["pet-luna"] = replace(cats["pet-luna"], avatar_key="resources/luna-2.jpg")
    mock_client.get_cats.return_value = cats
    frozen_time.tick(timedelta(hours=1))
    await _refresh(hass, config_entry)
    assert not old.exists()
    new = avatars / f"pet-luna.{key_hash('resources/luna-2.jpg')}.jpg"
    assert new.read_bytes() == b"luna-2"


async def test_forget_deletes_the_files_of_a_visit(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A forgotten visit loses its files."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    await mirror.async_forget("ev-1")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert list(day_folder(media_dir).iterdir()) == []


async def test_removing_the_entry_deletes_the_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """Removing the entry deletes the whole folder."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert (media_dir / ".siipet").exists()
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert not (media_dir / ".siipet").exists()


async def test_unload_stops_the_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The entry unloads with the copy running."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_a_downloading_job_is_not_queued_again(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """The initial queue and the backfill do not download the same file twice."""
    cats = {
        pet_id: replace(cat, avatar_key=None)
        for pet_id, cat in mock_client.get_cats.return_value.items()
    }
    mock_client.get_cats.return_value = cats
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert s3_gets(aioclient_mock, "events/ev-1/cover.jpg") == 1
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1


async def test_unload_stops_a_daily_run_in_progress(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """Unloading while the daily backfill waits on a day read drops that day."""
    next_run = datetime.fromisoformat("2026-09-27T00:05:00+00:00")
    old_day = next_run.date() - timedelta(days=9)
    old = mirror_visit(start=mirror_visit().start - timedelta(days=8))
    armed = False
    waiting = asyncio.Event()
    release = asyncio.Event()

    async def get_day(requested: Any, **_: Any) -> Any:
        if armed and requested == old_day:
            waiting.set()
            await release.wait()
            return replace(fixture_day(), visits=(old,))
        return replace(fixture_day(), visits=())

    mock_client.get_day.side_effect = get_day
    # The fixture credentials expire before the clock reaches the next day.
    mock_client.get_media_credentials.return_value = replace(
        mock_client.get_media_credentials.return_value,
        expires=next_run + timedelta(days=1),
    )
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 10)

    armed = True
    frozen_time.move_to(next_run)
    async_fire_time_changed(hass, next_run)
    await hass.async_block_till_done()
    await asyncio.wait_for(waiting.wait(), timeout=1)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 0
    assert not day_folder(media_dir, old_day).exists()


async def test_retry_of_an_older_day_does_not_wait_for_the_daily_run(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A failed download of a day outside the polled window retries on an update."""
    old_day = TODAY - timedelta(days=9)
    old = mirror_visit(start=mirror_visit().start - timedelta(days=9))
    serve_days(mock_client, {old_day: (old,)})
    statuses = [500, 200]

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(
            method, url, status=statuses.pop(0), response=VIDEO
        )

    aioclient_mock.get(S3 + "events/ev-1/video.mp4", side_effect=respond)
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 10)
    assert not (day_folder(media_dir, old_day) / "ev-1.mp4").exists()

    frozen_time.tick(timedelta(minutes=1))
    await _refresh(hass, config_entry)
    assert not (day_folder(media_dir, old_day) / "ev-1.mp4").exists()

    frozen_time.tick(timedelta(minutes=5))
    await _refresh(hass, config_entry)
    assert (day_folder(media_dir, old_day) / "ev-1.mp4").read_bytes() == VIDEO


async def test_a_failed_backfill_day_does_not_stop_the_others(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A day read that fails during the backfill does not stop the other days."""
    day8 = TODAY - timedelta(days=8)
    day9 = TODAY - timedelta(days=9)
    visit9 = mirror_visit(
        event_id="ev-9", start=mirror_visit().start - timedelta(days=9)
    )

    async def get_day(requested: Any, **_: Any) -> Any:
        if requested == day8:
            raise SiiPetConnectionError("The connection failed")
        if requested == day9:
            return replace(fixture_day(), visits=(visit9,))
        return replace(fixture_day(), visits=())

    mock_client.get_day.side_effect = get_day
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 10)
    assert (day_folder(media_dir, day9) / "ev-9.mp4").read_bytes() == VIDEO


async def test_a_write_failure_at_runtime_stops_the_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A MediaStoreError while writing a file stops the copy and raises an issue."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    with patch(
        "custom_components.siipet.media_store.MediaStore.async_write",
        side_effect=MediaStoreError("The store could not write a file"),
    ):
        await setup_mirror(hass, config_entry, 7)
    assert config_entry.state is ConfigEntryState.LOADED
    assert _issue(hass, ISSUE_FOLDER) is not None

    calls_before = aioclient_mock.call_count
    await _refresh(hass, config_entry)
    assert aioclient_mock.call_count == calls_before


async def test_cleanup_error_at_setup_stops_the_copy_and_raises_an_issue(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """An OSError while deleting old days leaves the entry loaded, with an issue."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    with patch(
        "custom_components.siipet.media_store.MediaStore._delete_days_before",
        side_effect=OSError,
    ):
        await setup_mirror(hass, config_entry, 7)
    assert config_entry.state is ConfigEntryState.LOADED
    assert _issue(hass, ISSUE_FOLDER) is not None
    assert aioclient_mock.call_count == 0


async def test_forget_during_a_download_stores_nothing(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """Forgetting a visit while its recording downloads leaves nothing stored."""
    serve_days(mock_client, {TODAY: (mirror_visit(cover_key=None, stool_key=None),)})
    started = asyncio.Event()
    release = asyncio.Event()

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        started.set()
        await release.wait()
        return AiohttpClientMockResponse(method, url, response=VIDEO)

    aioclient_mock.get(S3 + "events/ev-1/video.mp4", side_effect=respond)
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7, wait_for_downloads=False)
    await asyncio.wait_for(started.wait(), timeout=1)

    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    await mirror.async_forget("ev-1")
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    assert not (day_folder(media_dir) / "ev-1.mp4").exists()
    assert list(day_folder(media_dir).iterdir()) == []


async def test_an_unexpected_download_error_is_recorded_as_a_failure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unexpected error during a download does not stop the worker.

    The log names only the type of the error, with no message or traceback.
    """
    serve_days(mock_client, {TODAY: (mirror_visit(),)})

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        raise RuntimeError("events/ev-1/cover.jpg")

    aioclient_mock.get(S3 + "events/ev-1/cover.jpg", side_effect=respond)
    mock_s3(aioclient_mock)
    with caplog.at_level(logging.DEBUG, logger="custom_components.siipet"):
        await setup_mirror(hass, config_entry, 7)
    records = [
        record
        for record in caplog.records
        if record.name == "custom_components.siipet.media_mirror"
    ]
    assert [record.getMessage() for record in records] == [
        "The local media copy hit an unexpected error (RuntimeError)"
    ]
    assert records[0].exc_info is None
    assert "events/ev-1" not in caplog.text
    assert not (day_folder(media_dir) / "ev-1.cover.jpg").exists()
    assert (day_folder(media_dir) / "ev-1.stool.jpg").exists()
    assert (day_folder(media_dir) / "ev-1.mp4").exists()
    assert s3_gets(aioclient_mock, "events/ev-1/cover.jpg") == 1

    frozen_time.tick(timedelta(minutes=1))
    await _refresh(hass, config_entry)
    assert s3_gets(aioclient_mock, "events/ev-1/cover.jpg") == 1

    frozen_time.tick(timedelta(minutes=5))
    await _refresh(hass, config_entry)
    assert s3_gets(aioclient_mock, "events/ev-1/cover.jpg") == 2


async def test_a_new_avatar_key_is_not_blocked_by_the_old_keys_backoff(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A cat's new avatar key downloads even while the old key still waits out its backoff."""
    serve_days(mock_client, {})
    aioclient_mock.get(S3 + "resources/luna.jpg", status=404)
    mock_s3(aioclient_mock, **{"resources/luna-2.jpg": b"luna-2"})
    await setup_mirror(hass, config_entry, 7)
    assert s3_gets(aioclient_mock, "resources/luna.jpg") == 1

    cats = dict(mock_client.get_cats.return_value)
    cats["pet-luna"] = replace(cats["pet-luna"], avatar_key="resources/luna-2.jpg")
    mock_client.get_cats.return_value = cats
    frozen_time.tick(timedelta(hours=1))
    await _refresh(hass, config_entry)

    avatars = media_dir / ".siipet" / "avatars"
    new = avatars / f"pet-luna.{key_hash('resources/luna-2.jpg')}.jpg"
    assert new.read_bytes() == b"luna-2"
    assert s3_gets(aioclient_mock, "resources/luna.jpg") == 1


async def test_forget_during_a_failing_download_is_not_retried(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A visit forgotten during a download that then fails does not come back."""
    serve_days(mock_client, {TODAY: (mirror_visit(cover_key=None, stool_key=None),)})
    started = asyncio.Event()
    release = asyncio.Event()

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        started.set()
        await release.wait()
        return AiohttpClientMockResponse(method, url, status=500)

    aioclient_mock.get(S3 + "events/ev-1/video.mp4", side_effect=respond)
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7, wait_for_downloads=False)
    await asyncio.wait_for(started.wait(), timeout=1)

    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    await mirror.async_forget("ev-1")
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    # As after a real deletion, the visit no longer comes back from the API.
    serve_days(mock_client, {})
    frozen_time.tick(timedelta(minutes=6))
    await _refresh(hass, config_entry)
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1
    assert not day_folder(media_dir).exists()


async def test_a_polled_days_failure_does_not_retry_a_key_that_left_the_data(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A failed recording of a polled day is not retried once it leaves the current data."""
    serve_days(mock_client, {TODAY: (mirror_visit(video_md5=md5_hex(b"other")),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert not (day_folder(media_dir) / "ev-1.mp4").exists()
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1

    # The current data no longer has a cloud recording for this visit.
    serve_days(mock_client, {TODAY: (mirror_visit(cloud_stored=False),)})
    frozen_time.tick(timedelta(minutes=6))
    await _refresh(hass, config_entry)
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1
    assert not (day_folder(media_dir) / "ev-1.mp4").exists()


async def test_a_changed_recording_is_not_blocked_by_the_old_hashs_backoff(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A polled visit's changed recording downloads without waiting for the old backoff."""
    new_video = b"video-ev-1-new"
    video: dict[str, bytes] = {"data": VIDEO}

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, response=video["data"])

    aioclient_mock.get(S3 + "events/ev-1/video.mp4", side_effect=respond)
    serve_days(mock_client, {TODAY: (mirror_visit(video_md5=md5_hex(b"other")),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert not (day_folder(media_dir) / "ev-1.mp4").exists()

    video["data"] = new_video
    serve_days(
        mock_client,
        {
            TODAY: (
                mirror_visit(video_size=len(new_video), video_md5=md5_hex(new_video)),
            )
        },
    )
    frozen_time.tick(timedelta(minutes=1))
    await _refresh(hass, config_entry)
    assert (day_folder(media_dir) / "ev-1.mp4").read_bytes() == new_video


async def test_a_deleted_visit_does_not_come_back_from_a_backfill_read(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A day read that started before a delete does not store the deleted visit."""
    old_day = TODAY - timedelta(days=9)
    old = mirror_visit(start=mirror_visit().start - timedelta(days=9))
    waiting = asyncio.Event()
    release = asyncio.Event()

    async def get_day(requested: Any, **_: Any) -> Any:
        if requested == old_day:
            waiting.set()
            await release.wait()
            return replace(fixture_day(), visits=(old,))
        return replace(fixture_day(), visits=())

    mock_client.get_day.side_effect = get_day
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 10, wait_for_downloads=False)
    await asyncio.wait_for(waiting.wait(), timeout=1)

    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    await mirror.async_forget("ev-1")
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)

    for key in ("events/ev-1/video.mp4", "events/ev-1/cover.jpg"):
        assert s3_gets(aioclient_mock, key) == 0
    assert not day_folder(media_dir, old_day).exists()
    assert mirror.stats() == {"queued": 0, "failing": 0}


async def test_forget_drops_a_failed_job_of_an_unpolled_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
    media_dir: Path,
) -> None:
    """A forgotten visit of a day that is not polled gets no later retry."""
    old_day = TODAY - timedelta(days=9)
    old = mirror_visit(
        start=mirror_visit().start - timedelta(days=9), cover_key=None, stool_key=None
    )
    serve_days(mock_client, {old_day: (old,)})
    aioclient_mock.get(S3 + "events/ev-1/video.mp4", status=500)
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 10)
    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    assert mirror.stats() == {"queued": 0, "failing": 1}

    await mirror.async_forget("ev-1")
    assert mirror.stats() == {"queued": 0, "failing": 0}
    frozen_time.tick(timedelta(minutes=6))
    await _refresh(hass, config_entry)
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1
    assert not day_folder(media_dir, old_day).exists()


@pytest.mark.parametrize(
    ("changes", "gone"),
    [
        ({"stool_key": None, "stool_size": None}, "ev-1.stool.jpg"),
        ({"cloud_stored": False}, "ev-1.mp4"),
    ],
)
async def test_a_removed_media_key_deletes_its_file(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
    changes: dict[str, Any],
    gone: str,
) -> None:
    """A stool photo or a recording that left the current data leaves the copy."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    folder = day_folder(media_dir)
    assert (folder / gone).exists()

    serve_days(mock_client, {TODAY: (mirror_visit(**changes),)})
    await _refresh(hass, config_entry)
    assert sorted(path.name for path in folder.iterdir()) == sorted(
        {"ev-1.mp4", "ev-1.cover.jpg", "ev-1.stool.jpg"} - {gone}
    )


async def test_a_changed_size_downloads_the_file_again(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A stored file whose size no longer matches the current data is replaced."""
    new_cover = b"cover-ev-1-new"
    cover = {"data": COVER}

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, response=cover["data"])

    aioclient_mock.get(S3 + "events/ev-1/cover.jpg", side_effect=respond)
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert (day_folder(media_dir) / "ev-1.cover.jpg").read_bytes() == COVER

    cover["data"] = new_cover
    serve_days(mock_client, {TODAY: (mirror_visit(cover_size=len(new_cover)),)})
    await _refresh(hass, config_entry)
    assert (day_folder(media_dir) / "ev-1.cover.jpg").read_bytes() == new_cover
    assert s3_gets(aioclient_mock, "events/ev-1/cover.jpg") == 2
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 1


@pytest.mark.parametrize(("more", "kept"), [(False, False), (True, True)])
async def test_a_visit_that_left_its_polled_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
    more: bool,
    kept: bool,
) -> None:
    """A complete day list without the visit deletes its files, a partial one does not."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert (day_folder(media_dir) / "ev-1.mp4").exists()

    mock_client.get_day.side_effect = lambda requested, **_: replace(
        fixture_day(), visits=(), more=more and requested == TODAY
    )
    await _refresh(hass, config_entry)
    assert (day_folder(media_dir) / "ev-1.mp4").exists() is kept
    assert (day_folder(media_dir) / "ev-1.cover.jpg").exists() is kept


def _no_avatars(mock_client: AsyncMock) -> None:
    mock_client.get_cats.return_value = {
        pet_id: replace(cat, avatar_key=None)
        for pet_id, cat in mock_client.get_cats.return_value.items()
    }


async def test_free_space_counts_the_size_of_each_file(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """With room for the images but not for the recording, only the images download."""
    _no_avatars(mock_client)
    serve_days(mock_client, {TODAY: (mirror_visit(video_size=100 * 1024**2),)})
    mock_s3(aioclient_mock)
    with patch(
        "custom_components.siipet.media_store.shutil.disk_usage",
        return_value=SimpleNamespace(free=MIN_FREE_BYTES + 50 * 1024**2),
    ):
        await setup_mirror(hass, config_entry, 7)
    assert (day_folder(media_dir) / "ev-1.cover.jpg").exists()
    assert (day_folder(media_dir) / "ev-1.stool.jpg").exists()
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == 0
    assert _issue(hass, ISSUE_DISK_FULL) is not None


async def test_free_space_counts_a_file_without_a_size_as_the_allowance(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A file without a known size needs room for the allowance."""
    _no_avatars(mock_client)
    serve_days(mock_client, {TODAY: (mirror_visit(cover_size=None),)})
    mock_s3(aioclient_mock)
    with patch(
        "custom_components.siipet.media_store.shutil.disk_usage",
        return_value=SimpleNamespace(free=MIN_FREE_BYTES + UNKNOWN_SIZE_ALLOWANCE - 1),
    ):
        await setup_mirror(hass, config_entry, 7)
    assert s3_gets(aioclient_mock, "events/ev-1/cover.jpg") == 0
    assert _issue(hass, ISSUE_DISK_FULL) is not None


async def test_low_disk_space_keeps_the_queue(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A day that is not polled downloads on the next update after space returns."""
    old_day = TODAY - timedelta(days=9)
    old = mirror_visit(start=mirror_visit().start - timedelta(days=9))
    serve_days(mock_client, {old_day: (old,)})
    mock_s3(aioclient_mock)
    with patch(
        "custom_components.siipet.media_store.shutil.disk_usage",
        return_value=SimpleNamespace(free=MIN_FREE_BYTES - 1),
    ):
        await setup_mirror(hass, config_entry, 10)
    assert aioclient_mock.call_count == 0
    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    assert mirror.stats()["queued"] == 5

    await _refresh(hass, config_entry)
    assert (day_folder(media_dir, old_day) / "ev-1.mp4").read_bytes() == VIDEO
    assert _issue(hass, ISSUE_DISK_FULL) is None


async def test_full_disk_during_a_write_pauses_the_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A write that finds the disk full pauses the copy until a later update."""
    _no_avatars(mock_client)
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)

    class FullDisk:
        def write(self, data: bytes) -> int:
            raise OSError(errno.ENOSPC, "No space left on device")

        def close(self) -> None:
            pass

    def open_part(part: Path) -> FullDisk:
        part.parent.mkdir(parents=True, exist_ok=True)
        return FullDisk()

    with patch(
        "custom_components.siipet.media_store._open_part", side_effect=open_part
    ):
        await setup_mirror(hass, config_entry, 7)
    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    assert mirror.running
    assert _issue(hass, ISSUE_DISK_FULL) is not None
    assert _issue(hass, ISSUE_FOLDER) is None
    assert s3_gets(aioclient_mock, "events/ev-1/cover.jpg") == 1
    assert mirror.stats() == {"queued": 3, "failing": 0}

    await _refresh(hass, config_entry)
    assert (day_folder(media_dir) / "ev-1.cover.jpg").read_bytes() == COVER
    assert (day_folder(media_dir) / "ev-1.mp4").read_bytes() == VIDEO
    assert _issue(hass, ISSUE_DISK_FULL) is None


async def test_a_credentials_failure_waits_for_the_next_update(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """Without media credentials, the copy asks once and records no failures."""
    credentials = mock_client.get_media_credentials.return_value
    mock_client.get_media_credentials.side_effect = SiiPetConnectionError("down")
    old_day = TODAY - timedelta(days=9)
    old = mirror_visit(event_id="ev-9", start=mirror_visit().start - timedelta(days=9))

    async def get_day(requested: Any, **_: Any) -> Any:
        # Each read of a day that is not polled lets the downloads run.
        await asyncio.sleep(0)
        visits = {TODAY: (mirror_visit(),), old_day: (old,)}.get(requested, ())
        return replace(fixture_day(), visits=visits)

    mock_client.get_day.side_effect = get_day
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 10)
    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    assert mock_client.get_media_credentials.await_count == 1
    assert mirror.stats()["failing"] == 0
    assert aioclient_mock.call_count == 0

    mock_client.get_media_credentials.side_effect = None
    mock_client.get_media_credentials.return_value = credentials
    await _refresh(hass, config_entry)
    assert (day_folder(media_dir) / "ev-1.mp4").read_bytes() == VIDEO
    assert (day_folder(media_dir, old_day) / "ev-9.mp4").read_bytes() == VIDEO
    assert mirror.stats() == {"queued": 0, "failing": 0}


async def test_failed_downloads_wait_longer_each_time(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A file that keeps failing waits 5 minutes, 30 minutes, 2 hours, then 24 hours."""
    mock_client.get_media_credentials.return_value = replace(
        mock_client.get_media_credentials.return_value,
        expires=datetime.fromisoformat("2026-10-01T00:00:00+00:00"),
    )
    serve_days(mock_client, {TODAY: (mirror_visit(video_md5=md5_hex(b"other")),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    gets = 1
    assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == gets

    for delay in (
        timedelta(minutes=5),
        timedelta(minutes=30),
        timedelta(hours=2),
        timedelta(hours=24),
        timedelta(hours=24),
    ):
        frozen_time.tick(delay - timedelta(minutes=1))
        await _refresh(hass, config_entry)
        assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == gets
        frozen_time.tick(timedelta(minutes=1))
        await _refresh(hass, config_entry)
        gets += 1
        assert s3_gets(aioclient_mock, "events/ev-1/video.mp4") == gets
